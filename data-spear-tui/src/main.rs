use anyhow::Result;
use crossterm::{
    event::{Event, EventStream, KeyCode, KeyEvent, KeyEventKind, KeyModifiers},
    execute,
    terminal::{disable_raw_mode, enable_raw_mode, EnterAlternateScreen, LeaveAlternateScreen},
};
use futures::StreamExt;
use ratatui::{
    backend::CrosstermBackend,
    layout::{Constraint, Direction, Layout, Rect},
    style::{Color, Modifier, Style},
    text::{Line, Span, Text},
    widgets::{Block, BorderType, Borders, Paragraph, Wrap},
    Frame, Terminal,
};
use serde::{Deserialize, Serialize};
use std::{
    env, io,
    time::{Duration, Instant},
};
use tokio::sync::mpsc;

const DEFAULT_API: &str = "http://localhost:8000";

// Braille spinner frames for the loading animation.
const SPINNER: [&str; 10] = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];

fn spinner_frame(tick: usize) -> &'static str {
    SPINNER[tick % SPINNER.len()]
}

// Palette: one accent color used consistently, everything else neutral.
const ACCENT: Color = Color::Cyan;
const DIM: Color = Color::DarkGray;

// Setup-form field indices.
const F_URL: usize = 0;
const F_HOST: usize = 1;
const F_PORT: usize = 2;
const F_DB: usize = 3;
const F_USER: usize = 4;
const F_PASS: usize = 5;
const F_SSL: usize = 6;

#[derive(Serialize)]
struct ConnectRequest {
    dsn: Option<String>,
    host: String,
    port: u16,
    dbname: String,
    user: String,
    password: String,
    sslmode: Option<String>,
}

#[derive(Deserialize, Debug)]
struct ConnectResponse {
    #[allow(dead_code)]
    status: String,
    database: String,
    server: String,
}

#[derive(Serialize)]
struct QueryRequest {
    prompt: String,
    // User authorization for Tier 2 SQL (DDL, unbounded writes); set by the `!` prefix.
    allow_destructive: bool,
}

#[derive(Deserialize, Clone, Debug)]
struct Hit {
    id: String,
    score: f64,
    #[allow(dead_code)]
    text: String,
}

/// One SSE event from `/query/stream`, mirroring the backend agent loop.
#[derive(Deserialize, Debug, Clone)]
#[serde(tag = "type", rename_all = "snake_case")]
enum AgentEvent {
    Retrieval {
        count: usize,
    },
    Thinking {
        text: String,
    },
    ToolUse {
        name: String,
        #[serde(default)]
        detail: String,
    },
    ToolResult {
        name: String,
        ok: bool,
        #[serde(default)]
        detail: String,
    },
    Final {
        answer: String,
        #[serde(default)]
        hits: Vec<Hit>,
    },
    Error {
        message: String,
    },
}

/// A line in the agent's activity trace, shown live and kept for audit.
#[derive(Clone)]
enum Activity {
    Retrieval(usize),
    Thinking(String),
    Tool {
        name: String,
        detail: String,
        // None while the call is in flight; Some((ok, result summary)) once done.
        done: Option<(bool, String)>,
    },
}

fn tool_count(activity: &[Activity]) -> usize {
    activity
        .iter()
        .filter(|a| matches!(a, Activity::Tool { .. }))
        .count()
}

#[derive(Clone)]
struct Turn {
    question: String, // empty for system notes
    answer: String,
    hits: Vec<Hit>,
    tool_calls: usize,
    secs: u64,
    note: bool,
}

impl Turn {
    fn note(text: impl Into<String>) -> Self {
        Self {
            question: String::new(),
            answer: text.into(),
            hits: Vec::new(),
            tool_calls: 0,
            secs: 0,
            note: true,
        }
    }
}

struct PendingTurn {
    question: String,
    activity: Vec<Activity>,
    started: Instant,
}

#[derive(Debug, PartialEq)]
enum Status {
    Idle,
    Connecting,
    Querying,
    Ingesting,
    Error(String),
}

#[derive(PartialEq)]
enum Screen {
    Setup,
    Chat,
}

struct Field {
    label: &'static str,
    value: String,
    masked: bool,
}

impl Field {
    fn new(label: &'static str, value: &str, masked: bool) -> Self {
        Self {
            label,
            value: value.to_string(),
            masked,
        }
    }
}

struct App {
    screen: Screen,
    fields: Vec<Field>,
    focus: usize,
    input: String,
    history: Vec<String>,
    history_pos: Option<usize>,
    messages: Vec<Turn>,
    traces: Vec<Vec<Activity>>, // parallel to `messages`; empty for notes
    show_trace: bool,
    pending: Option<PendingTurn>,
    status: Status,
    scroll: u16,
    tick: usize,
    api_url: String,
    db_info: String,
}

impl App {
    fn new(api_url: String) -> Self {
        Self {
            screen: Screen::Setup,
            fields: vec![
                Field::new("Connection URL", "", false),
                Field::new("Host", "localhost", false),
                Field::new("Port", "5432", false),
                Field::new("Database", "postgres", false),
                Field::new("User", "postgres", false),
                Field::new("Password", "", true),
                Field::new("SSL mode", "", false),
            ],
            focus: F_HOST,
            input: String::new(),
            history: Vec::new(),
            history_pos: None,
            messages: Vec::new(),
            traces: Vec::new(),
            show_trace: true,
            pending: None,
            status: Status::Idle,
            scroll: 0,
            tick: 0,
            api_url,
            db_info: String::new(),
        }
    }

    fn busy(&self) -> bool {
        matches!(
            self.status,
            Status::Connecting | Status::Querying | Status::Ingesting
        )
    }

    fn push_note(&mut self, text: impl Into<String>) {
        self.messages.push(Turn::note(text));
        self.traces.push(Vec::new());
        self.scroll = 0;
    }
}

enum Msg {
    ConnectResult(Result<ConnectResponse, String>),
    Agent(AgentEvent),
    StreamFailed(String),
    StreamClosed,
    IngestResult(Result<String, String>),
}

#[tokio::main]
async fn main() -> Result<()> {
    let api_url = env::var("DATA_SPEAR_API").unwrap_or_else(|_| DEFAULT_API.to_string());

    enable_raw_mode()?;
    let mut stdout = io::stdout();
    execute!(stdout, EnterAlternateScreen)?;
    let backend = CrosstermBackend::new(stdout);
    let mut terminal = Terminal::new(backend)?;

    let result = run(&mut terminal, api_url).await;

    disable_raw_mode()?;
    execute!(terminal.backend_mut(), LeaveAlternateScreen)?;
    terminal.show_cursor()?;

    result
}

async fn run(terminal: &mut Terminal<CrosstermBackend<io::Stdout>>, api_url: String) -> Result<()> {
    let mut app = App::new(api_url);
    let mut events = EventStream::new();
    let (tx, mut rx) = mpsc::unbounded_channel::<Msg>();
    // If the API requires a bearer token (API_TOKEN on the server), send it on
    // every request from DATA_SPEAR_API_TOKEN.
    let mut headers = reqwest::header::HeaderMap::new();
    if let Ok(token) = env::var("DATA_SPEAR_API_TOKEN") {
        if let Ok(value) =
            reqwest::header::HeaderValue::from_str(&format!("Bearer {}", token))
        {
            headers.insert(reqwest::header::AUTHORIZATION, value);
        }
    }
    let client = reqwest::Client::builder()
        .default_headers(headers)
        .timeout(Duration::from_secs(120))
        .build()?;

    // Drives the spinner animation while a request is in flight.
    let mut ticker = tokio::time::interval(Duration::from_millis(80));

    loop {
        terminal.draw(|f| ui(f, &app))?;

        tokio::select! {
            Some(event) = events.next() => {
                if let Ok(Event::Key(key)) = event {
                    if key.kind != KeyEventKind::Press { continue; }
                    if handle_key(&mut app, key, &client, &tx) { break; }
                }
            }
            Some(msg) = rx.recv() => {
                match msg {
                    Msg::ConnectResult(Ok(resp)) => {
                        app.db_info = format!("{} · {}", resp.database, resp.server);
                        app.screen = Screen::Chat;
                        app.status = Status::Idle;
                    }
                    Msg::ConnectResult(Err(e)) => {
                        app.status = Status::Error(e);
                    }
                    Msg::Agent(evt) => apply_event(&mut app, evt),
                    Msg::StreamFailed(e) => fail_pending(&mut app, e),
                    Msg::StreamClosed => {
                        if matches!(app.status, Status::Querying) {
                            fail_pending(
                                &mut app,
                                "stream ended before a final answer".to_string(),
                            );
                        }
                    }
                    Msg::IngestResult(Ok(summary)) => {
                        app.push_note(format!("✓ {}", summary));
                        app.status = Status::Idle;
                    }
                    Msg::IngestResult(Err(e)) => {
                        app.push_note(format!("⚠ ingest failed: {}", e));
                        app.status = Status::Idle;
                    }
                }
            }
            _ = ticker.tick() => {
                if app.busy() {
                    app.tick = app.tick.wrapping_add(1);
                }
            }
        }
    }
    Ok(())
}

fn apply_event(app: &mut App, evt: AgentEvent) {
    match evt {
        AgentEvent::Retrieval { count } => {
            if let Some(p) = app.pending.as_mut() {
                p.activity.push(Activity::Retrieval(count));
            }
        }
        AgentEvent::Thinking { text } => {
            if let Some(p) = app.pending.as_mut() {
                p.activity.push(Activity::Thinking(text));
            }
        }
        AgentEvent::ToolUse { name, detail } => {
            if let Some(p) = app.pending.as_mut() {
                p.activity.push(Activity::Tool {
                    name,
                    detail,
                    done: None,
                });
            }
        }
        AgentEvent::ToolResult { name, ok, detail } => {
            if let Some(p) = app.pending.as_mut() {
                // Fill in the most recent in-flight call with this name.
                for act in p.activity.iter_mut().rev() {
                    if let Activity::Tool {
                        name: n, done: done @ None, ..
                    } = act
                    {
                        if *n == name {
                            *done = Some((ok, detail));
                            break;
                        }
                    }
                }
            }
        }
        AgentEvent::Final { answer, hits } => {
            if let Some(p) = app.pending.take() {
                app.messages.push(Turn {
                    question: p.question,
                    answer,
                    hits,
                    tool_calls: tool_count(&p.activity),
                    secs: p.started.elapsed().as_secs(),
                    note: false,
                });
                app.traces.push(p.activity);
            }
            app.status = Status::Idle;
            app.scroll = 0;
        }
        AgentEvent::Error { message } => fail_pending(app, message),
    }
}

fn fail_pending(app: &mut App, message: String) {
    if let Some(p) = app.pending.take() {
        app.messages.push(Turn {
            question: p.question,
            answer: format!("⚠ {}", message),
            hits: Vec::new(),
            tool_calls: tool_count(&p.activity),
            secs: p.started.elapsed().as_secs(),
            note: false,
        });
        app.traces.push(p.activity);
    }
    app.status = Status::Error(message);
}

fn handle_key(
    app: &mut App,
    key: KeyEvent,
    client: &reqwest::Client,
    tx: &mpsc::UnboundedSender<Msg>,
) -> bool {
    if key.modifiers.contains(KeyModifiers::CONTROL) {
        match key.code {
            KeyCode::Char('c') | KeyCode::Char('d') => return true,
            KeyCode::Char('t') => {
                app.show_trace = !app.show_trace;
                return false;
            }
            KeyCode::Char('l') => {
                if app.screen == Screen::Chat && !app.busy() {
                    app.messages.clear();
                    app.traces.clear();
                    app.scroll = 0;
                }
                return false;
            }
            _ => {}
        }
    }
    match app.screen {
        Screen::Setup => handle_setup_key(app, key, client, tx),
        Screen::Chat => handle_chat_key(app, key, client, tx),
    }
}

fn handle_setup_key(
    app: &mut App,
    key: KeyEvent,
    client: &reqwest::Client,
    tx: &mpsc::UnboundedSender<Msg>,
) -> bool {
    match key.code {
        KeyCode::Esc => return true,
        KeyCode::Tab | KeyCode::Down => {
            app.focus = (app.focus + 1) % app.fields.len();
        }
        KeyCode::BackTab | KeyCode::Up => {
            app.focus = (app.focus + app.fields.len() - 1) % app.fields.len();
        }
        KeyCode::Enter => {
            if !matches!(app.status, Status::Connecting) {
                submit_connect(app, client, tx);
            }
        }
        KeyCode::Backspace => {
            app.fields[app.focus].value.pop();
        }
        KeyCode::Char(c) => app.fields[app.focus].value.push(c),
        _ => {}
    }
    false
}

fn handle_chat_key(
    app: &mut App,
    key: KeyEvent,
    client: &reqwest::Client,
    tx: &mpsc::UnboundedSender<Msg>,
) -> bool {
    match key.code {
        KeyCode::Esc => {
            if app.input.is_empty() {
                return true;
            }
            app.input.clear();
            app.history_pos = None;
        }
        KeyCode::Enter => {
            let q = app.input.trim().to_string();
            if q.is_empty() || matches!(app.status, Status::Querying | Status::Ingesting) {
                return false;
            }
            app.input.clear();
            app.history_pos = None;
            if app.history.last() != Some(&q) {
                app.history.push(q.clone());
            }
            if let Some(cmd) = q.strip_prefix('/') {
                run_command(app, cmd, client, tx);
            } else if let Some(rest) = q.strip_prefix('!') {
                // `!` = the user authorizes Tier 2 (destructive/DDL) SQL for this request.
                let rest = rest.trim().to_string();
                if !rest.is_empty() {
                    submit_prompt(app, rest, true, client, tx);
                }
            } else {
                submit_prompt(app, q, false, client, tx);
            }
        }
        KeyCode::Backspace => {
            app.input.pop();
            app.history_pos = None;
        }
        KeyCode::Char(c) => {
            app.input.push(c);
            app.history_pos = None;
        }
        // ↑/↓ recall prompt history, like a shell; PgUp/PgDn scroll the transcript.
        KeyCode::Up => {
            if app.history.is_empty() {
                return false;
            }
            let pos = match app.history_pos {
                None => app.history.len() - 1,
                Some(0) => 0,
                Some(p) => p - 1,
            };
            app.history_pos = Some(pos);
            app.input = app.history[pos].clone();
        }
        KeyCode::Down => match app.history_pos {
            None => {}
            Some(p) if p + 1 >= app.history.len() => {
                app.history_pos = None;
                app.input.clear();
            }
            Some(p) => {
                app.history_pos = Some(p + 1);
                app.input = app.history[p + 1].clone();
            }
        },
        KeyCode::PageUp => app.scroll = app.scroll.saturating_add(10),
        KeyCode::PageDown => app.scroll = app.scroll.saturating_sub(10),
        _ => {}
    }
    false
}

fn run_command(
    app: &mut App,
    cmd: &str,
    client: &reqwest::Client,
    tx: &mpsc::UnboundedSender<Msg>,
) {
    match cmd.trim() {
        "help" => app.push_note(
            "commands: /help · /clear (also Ctrl+L) · /trace (also Ctrl+T) · /ingest\n\
             keys: Enter send · ↑↓ history · PgUp/PgDn scroll · Esc clear input / quit\n\
             prefix a prompt with ! to authorize destructive SQL (DROP/ALTER/unbounded writes)",
        ),
        "clear" => {
            app.messages.clear();
            app.traces.clear();
            app.scroll = 0;
        }
        "trace" => {
            app.show_trace = !app.show_trace;
            let state = if app.show_trace { "on" } else { "off" };
            app.push_note(format!("trace display {}", state));
        }
        "ingest" => {
            app.status = Status::Ingesting;
            app.tick = 0;
            let client = client.clone();
            let tx = tx.clone();
            let base = app.api_url.clone();
            tokio::spawn(async move {
                let result = run_ingest(&client, &base).await.map_err(|e| e.to_string());
                let _ = tx.send(Msg::IngestResult(result));
            });
        }
        other => app.push_note(format!("unknown command: /{} — try /help", other)),
    }
}

fn submit_prompt(
    app: &mut App,
    q: String,
    allow_destructive: bool,
    client: &reqwest::Client,
    tx: &mpsc::UnboundedSender<Msg>,
) {
    app.status = Status::Querying;
    app.tick = 0;
    app.scroll = 0;
    let shown = if allow_destructive {
        format!("! {}", q)
    } else {
        q.clone()
    };
    app.pending = Some(PendingTurn {
        question: shown,
        activity: Vec::new(),
        started: Instant::now(),
    });
    let client = client.clone();
    let tx = tx.clone();
    let url = app.api_url.clone();
    tokio::spawn(async move {
        match stream_query(&client, &url, &q, allow_destructive, &tx).await {
            Ok(()) => {
                let _ = tx.send(Msg::StreamClosed);
            }
            Err(e) => {
                let _ = tx.send(Msg::StreamFailed(e.to_string()));
            }
        }
    });
}

fn submit_connect(app: &mut App, client: &reqwest::Client, tx: &mpsc::UnboundedSender<Msg>) {
    let trimmed = |i: usize| app.fields[i].value.trim().to_string();
    let or_default = |i: usize, default: &str| {
        let v = app.fields[i].value.trim();
        if v.is_empty() {
            default.to_string()
        } else {
            v.to_string()
        }
    };
    let url = trimmed(F_URL);
    let ssl = trimmed(F_SSL);
    let req = ConnectRequest {
        dsn: if url.is_empty() { None } else { Some(url) },
        host: or_default(F_HOST, "localhost"),
        port: trimmed(F_PORT).parse().unwrap_or(5432),
        dbname: or_default(F_DB, "postgres"),
        user: or_default(F_USER, "postgres"),
        password: app.fields[F_PASS].value.clone(),
        sslmode: if ssl.is_empty() { None } else { Some(ssl) },
    };

    app.status = Status::Connecting;
    app.tick = 0;
    let client = client.clone();
    let tx = tx.clone();
    let base = app.api_url.clone();
    tokio::spawn(async move {
        let result = send_connect(&client, &base, &req)
            .await
            .map_err(|e| e.to_string());
        let _ = tx.send(Msg::ConnectResult(result));
    });
}

async fn send_connect(
    client: &reqwest::Client,
    base: &str,
    req: &ConnectRequest,
) -> anyhow::Result<ConnectResponse> {
    let url = format!("{}/connect", base);
    let resp = client.post(&url).json(req).send().await?;
    if !resp.status().is_success() {
        let status = resp.status();
        let body = resp.text().await.unwrap_or_default();
        return Err(anyhow::anyhow!("{}: {}", status, body));
    }
    Ok(resp.json::<ConnectResponse>().await?)
}

async fn run_ingest(client: &reqwest::Client, base: &str) -> anyhow::Result<String> {
    let url = format!("{}/ingest", base);
    let resp = client
        .post(&url)
        .timeout(Duration::from_secs(600))
        .send()
        .await?;
    if !resp.status().is_success() {
        let status = resp.status();
        let body = resp.text().await.unwrap_or_default();
        return Err(anyhow::anyhow!("{}: {}", status, body));
    }
    let counts: serde_json::Value = resp.json().await?;
    let summary = counts
        .as_object()
        .map(|m| {
            m.iter()
                .map(|(k, v)| format!("{} → {} records", k, v))
                .collect::<Vec<_>>()
                .join(", ")
        })
        .unwrap_or_else(|| counts.to_string());
    Ok(format!("ingested: {}", summary))
}

/// POST /query/stream and forward each SSE `data:` event over the channel.
async fn stream_query(
    client: &reqwest::Client,
    base: &str,
    prompt: &str,
    allow_destructive: bool,
    tx: &mpsc::UnboundedSender<Msg>,
) -> anyhow::Result<()> {
    let url = format!("{}/query/stream", base);
    let resp = client
        .post(&url)
        // Agent sessions can outlive the client default; give the stream room.
        .timeout(Duration::from_secs(600))
        .json(&QueryRequest {
            prompt: prompt.to_string(),
            allow_destructive,
        })
        .send()
        .await?;
    if !resp.status().is_success() {
        let status = resp.status();
        let body = resp.text().await.unwrap_or_default();
        return Err(anyhow::anyhow!("{}: {}", status, body));
    }

    let mut stream = resp.bytes_stream();
    let mut buf = String::new();
    while let Some(chunk) = stream.next().await {
        let chunk = chunk?;
        buf.push_str(&String::from_utf8_lossy(&chunk));
        // SSE frames are separated by a blank line.
        while let Some(pos) = buf.find("\n\n") {
            let frame: String = buf.drain(..pos + 2).collect();
            for line in frame.lines() {
                if let Some(data) = line.strip_prefix("data: ") {
                    match serde_json::from_str::<AgentEvent>(data) {
                        Ok(evt) => {
                            let _ = tx.send(Msg::Agent(evt));
                        }
                        Err(_) => continue, // ignore unknown event types
                    }
                }
            }
        }
    }
    Ok(())
}

// ── rendering ────────────────────────────────────────────────────────────────

fn ui(f: &mut Frame, app: &App) {
    match app.screen {
        Screen::Setup => ui_setup(f, app),
        Screen::Chat => ui_chat(f, app),
    }
}

fn truncate(s: &str, max: usize) -> String {
    let mut out: String = s.chars().take(max).collect();
    if s.chars().count() > max {
        out.push('…');
    }
    out
}

fn centered(area: Rect, w: u16, h: u16) -> Rect {
    let w = w.min(area.width);
    let h = h.min(area.height);
    Rect {
        x: area.x + (area.width - w) / 2,
        y: area.y + (area.height - h) / 2,
        width: w,
        height: h,
    }
}

fn render_header(f: &mut Frame, area: Rect, app: &App) {
    let right = if app.db_info.is_empty() {
        app.api_url.clone()
    } else {
        app.db_info.clone()
    };
    let left = vec![
        Span::styled("✦ ", Style::default().fg(ACCENT)),
        Span::styled(
            "data-spear",
            Style::default().fg(ACCENT).add_modifier(Modifier::BOLD),
        ),
        Span::styled("  agentic sql", Style::default().fg(DIM)),
    ];
    f.render_widget(
        Paragraph::new(two_sided(left, vec![Span::styled(right, Style::default().fg(DIM))], area.width)),
        Rect { height: 1, ..area },
    );
    if area.height > 1 {
        let rule = "─".repeat(area.width as usize);
        f.render_widget(
            Paragraph::new(Line::from(Span::styled(rule, Style::default().fg(DIM)))),
            Rect {
                y: area.y + 1,
                height: 1,
                ..area
            },
        );
    }
}

/// Compose a single line with left- and right-aligned span groups.
fn two_sided(left: Vec<Span<'static>>, right: Vec<Span<'static>>, width: u16) -> Line<'static> {
    let used: usize = left
        .iter()
        .chain(right.iter())
        .map(|s| s.content.chars().count())
        .sum();
    let pad = (width as usize).saturating_sub(used + 1);
    let mut spans = left;
    spans.push(Span::raw(" ".repeat(pad)));
    spans.extend(right);
    Line::from(spans)
}

fn ui_setup(f: &mut Frame, app: &App) {
    let area = f.area();
    let chunks = Layout::default()
        .direction(Direction::Vertical)
        .constraints([Constraint::Length(2), Constraint::Min(5)])
        .split(area);
    render_header(f, chunks[0], app);

    let card = centered(chunks[1], 62, 15);
    let mut lines: Vec<Line> = vec![
        Line::from(Span::styled(
            "Defaults connect to a local database. For a hosted service,",
            Style::default().fg(DIM),
        )),
        Line::from(Span::styled(
            "paste a connection URL or fill in the fields.",
            Style::default().fg(DIM),
        )),
        Line::raw(""),
    ];

    for (i, field) in app.fields.iter().enumerate() {
        let focused = i == app.focus;
        let shown = if field.masked {
            "•".repeat(field.value.chars().count())
        } else {
            field.value.clone()
        };
        let label_style = if focused {
            Style::default().fg(ACCENT).add_modifier(Modifier::BOLD)
        } else {
            Style::default().fg(Color::Gray)
        };
        let marker = if focused { "› " } else { "  " };
        let cursor = if focused { "▌" } else { "" };
        lines.push(Line::from(vec![
            Span::styled(marker, Style::default().fg(ACCENT)),
            Span::styled(format!("{:>14}  ", field.label), label_style),
            Span::raw(shown),
            Span::styled(cursor, Style::default().fg(ACCENT)),
        ]));
    }

    lines.push(Line::raw(""));
    let status_line = match &app.status {
        Status::Connecting => Line::from(Span::styled(
            format!("{} connecting…", spinner_frame(app.tick)),
            Style::default().fg(Color::Yellow),
        )),
        Status::Error(e) => Line::from(Span::styled(
            format!("✗ {}", truncate(e, 110)),
            Style::default().fg(Color::Red),
        )),
        _ => Line::from(Span::styled(
            "Tab next · Enter connect · Esc quit",
            Style::default().fg(DIM),
        )),
    };
    lines.push(status_line);

    let form = Paragraph::new(Text::from(lines))
        .block(
            Block::default()
                .borders(Borders::ALL)
                .border_type(BorderType::Rounded)
                .border_style(Style::default().fg(DIM))
                .title(Span::styled(
                    " connect to postgresql ",
                    Style::default().fg(ACCENT).add_modifier(Modifier::BOLD),
                )),
        )
        .wrap(Wrap { trim: false });
    f.render_widget(form, card);
}

fn ui_chat(f: &mut Frame, app: &App) {
    let area = f.area();
    let chunks = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Length(2),
            Constraint::Min(4),
            Constraint::Length(3),
            Constraint::Length(1),
        ])
        .split(area);

    render_header(f, chunks[0], app);
    render_transcript(f, chunks[1], app);
    render_composer(f, chunks[2], app);
    render_footer(f, chunks[3], app);
}

/// Render one activity trace; `tick` is Some(..) while live (animates the in-flight call).
fn activity_lines(activity: &[Activity], tick: Option<usize>) -> Vec<Line<'static>> {
    let dim = Style::default().fg(DIM);
    let mut lines = Vec::new();
    for act in activity {
        match act {
            Activity::Retrieval(n) => {
                lines.push(Line::from(Span::styled(
                    format!("  ◈ retrieved {} context chunks", n),
                    dim,
                )));
            }
            Activity::Thinking(t) => {
                lines.push(Line::from(Span::styled(
                    format!("  ✻ {}", truncate(t, 110)),
                    Style::default()
                        .fg(Color::Magenta)
                        .add_modifier(Modifier::ITALIC | Modifier::DIM),
                )));
            }
            Activity::Tool { name, detail, done } => match done {
                None => {
                    let frame = tick.map(spinner_frame).unwrap_or("⚒");
                    lines.push(Line::from(vec![
                        Span::styled(
                            format!("  {} {} ", frame, name),
                            Style::default()
                                .fg(Color::Yellow)
                                .add_modifier(Modifier::BOLD),
                        ),
                        Span::styled(truncate(detail, 90), Style::default().fg(Color::Yellow)),
                    ]));
                }
                Some((ok, result)) => {
                    let (mark, color) = if *ok {
                        ("✓", Color::Green)
                    } else {
                        ("✗", Color::Red)
                    };
                    let mut spans = vec![
                        Span::styled(format!("  {} ", mark), Style::default().fg(color)),
                        Span::styled(format!("{} ", name), dim.add_modifier(Modifier::BOLD)),
                        Span::styled(truncate(detail, 70), dim),
                    ];
                    if !result.is_empty() {
                        spans.push(Span::styled(format!(" → {}", truncate(result, 60)), dim));
                    }
                    lines.push(Line::from(spans));
                }
            },
        }
    }
    lines
}

fn question_line(q: &str) -> Line<'static> {
    Line::from(vec![
        Span::styled(
            "› ",
            Style::default().fg(ACCENT).add_modifier(Modifier::BOLD),
        ),
        Span::styled(q.to_string(), Style::default().add_modifier(Modifier::BOLD)),
    ])
}

fn welcome_lines(app: &App) -> Vec<Line<'static>> {
    let mut lines = vec![
        Line::raw(""),
        Line::from(vec![
            Span::styled("  ✦ ", Style::default().fg(ACCENT)),
            Span::styled(
                "Welcome to Data-Spear",
                Style::default().add_modifier(Modifier::BOLD),
            ),
        ]),
        Line::from(Span::styled(
            "    An agent that plans, queries, and verifies over your live database.",
            Style::default().fg(DIM),
        )),
        Line::raw(""),
        Line::from(Span::styled(
            format!("    connected to {}", app.db_info),
            Style::default().fg(Color::Green),
        )),
        Line::raw(""),
        Line::from(Span::styled("    try:", Style::default().fg(DIM))),
    ];
    for ex in [
        "what tables do we have and how are they related?",
        "how many orders shipped in the last 7 days?",
        "find customers with no orders since January",
    ] {
        lines.push(Line::from(vec![
            Span::styled("      › ", Style::default().fg(ACCENT)),
            Span::styled(ex.to_string(), Style::default().fg(Color::Gray)),
        ]));
    }
    lines.push(Line::raw(""));
    lines.push(Line::from(Span::styled(
        "    /help for commands",
        Style::default().fg(DIM),
    )));
    lines
}

fn render_transcript(f: &mut Frame, area: Rect, app: &App) {
    let mut lines: Vec<Line> = Vec::new();

    if app.messages.is_empty() && app.pending.is_none() {
        lines = welcome_lines(app);
    }

    for (i, turn) in app.messages.iter().enumerate() {
        if i > 0 || !lines.is_empty() {
            lines.push(Line::raw(""));
        }
        if turn.note {
            for ln in turn.answer.lines() {
                lines.push(Line::from(Span::styled(
                    format!("◆ {}", ln),
                    Style::default().fg(DIM).add_modifier(Modifier::ITALIC),
                )));
            }
            continue;
        }
        lines.push(question_line(&turn.question));
        if app.show_trace {
            if let Some(trace) = app.traces.get(i) {
                lines.extend(activity_lines(trace, None));
            }
        } else if turn.tool_calls > 0 {
            lines.push(Line::from(Span::styled(
                format!(
                    "  ⚒ {} tool calls · {}s · Ctrl+T to show trace",
                    turn.tool_calls, turn.secs
                ),
                Style::default().fg(DIM).add_modifier(Modifier::ITALIC),
            )));
        }
        for ln in turn.answer.lines() {
            let style = if ln.starts_with('⚠') {
                Style::default().fg(Color::Red)
            } else {
                Style::default()
            };
            lines.push(Line::from(Span::styled(format!("  {}", ln), style)));
        }
        if !turn.hits.is_empty() {
            let refs = turn
                .hits
                .iter()
                .map(|h| format!("[{}] {:.2}", h.id, h.score))
                .collect::<Vec<_>>()
                .join(" · ");
            lines.push(Line::from(Span::styled(
                format!("  └ sources {}", truncate(&refs, 140)),
                Style::default().fg(DIM),
            )));
        }
    }

    // Live view of the in-flight agent turn: question, streamed activity, spinner.
    if let Some(p) = &app.pending {
        if !lines.is_empty() {
            lines.push(Line::raw(""));
        }
        lines.push(question_line(&p.question));
        lines.extend(activity_lines(&p.activity, Some(app.tick)));
        lines.push(Line::from(vec![
            Span::styled(
                format!("  {} ", spinner_frame(app.tick)),
                Style::default()
                    .fg(Color::Yellow)
                    .add_modifier(Modifier::BOLD),
            ),
            Span::styled(
                format!("working… {}s", p.started.elapsed().as_secs()),
                Style::default()
                    .fg(Color::Yellow)
                    .add_modifier(Modifier::ITALIC),
            ),
        ]));
    }

    let total = lines.len() as u16;
    let visible = area.height;
    let max_scroll = total.saturating_sub(visible);
    let scroll_y = max_scroll.saturating_sub(app.scroll.min(max_scroll));
    let para = Paragraph::new(Text::from(lines))
        .wrap(Wrap { trim: false })
        .scroll((scroll_y, 0));
    f.render_widget(para, area);
}

fn render_composer(f: &mut Frame, area: Rect, app: &App) {
    let border_color = match &app.status {
        Status::Querying | Status::Ingesting => Color::Yellow,
        Status::Error(_) => Color::Red,
        _ => DIM,
    };
    let content = if app.input.is_empty() {
        Line::from(vec![
            Span::styled("› ", Style::default().fg(ACCENT)),
            Span::styled(
                "Ask your database anything… (/help for commands)",
                Style::default().fg(DIM),
            ),
        ])
    } else {
        Line::from(vec![
            Span::styled("› ", Style::default().fg(ACCENT)),
            Span::raw(app.input.clone()),
            Span::styled("▌", Style::default().fg(ACCENT)),
        ])
    };
    let para = Paragraph::new(content).block(
        Block::default()
            .borders(Borders::ALL)
            .border_type(BorderType::Rounded)
            .border_style(Style::default().fg(border_color)),
    );
    f.render_widget(para, area);
}

fn render_footer(f: &mut Frame, area: Rect, app: &App) {
    let left = vec![Span::styled(
        " Enter send · ↑↓ history · PgUp/PgDn scroll · Ctrl+T trace · Ctrl+L clear · Esc quit",
        Style::default().fg(DIM),
    )];
    let right = match &app.status {
        Status::Idle => vec![Span::styled("● ready ", Style::default().fg(Color::Green))],
        Status::Connecting => vec![Span::styled(
            format!("{} connecting… ", spinner_frame(app.tick)),
            Style::default().fg(Color::Yellow),
        )],
        Status::Ingesting => vec![Span::styled(
            format!("{} ingesting… ", spinner_frame(app.tick)),
            Style::default().fg(Color::Yellow),
        )],
        Status::Querying => {
            let (steps, secs) = app
                .pending
                .as_ref()
                .map(|p| (tool_count(&p.activity), p.started.elapsed().as_secs()))
                .unwrap_or((0, 0));
            vec![Span::styled(
                format!(
                    "{} working {}s · {} tools ",
                    spinner_frame(app.tick),
                    secs,
                    steps
                ),
                Style::default().fg(Color::Yellow),
            )]
        }
        Status::Error(e) => vec![Span::styled(
            format!("✗ {} ", truncate(e, 60)),
            Style::default().fg(Color::Red),
        )],
    };
    f.render_widget(Paragraph::new(two_sided(left, right, area.width)), area);
}
