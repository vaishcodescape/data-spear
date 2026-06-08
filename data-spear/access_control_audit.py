import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import psycopg2
logger = logging.getLogger("omnigraph.access_control")


# Role checks, sensitivity-based access, and audit reporting.
class AccessControlManager:

    def __init__(self, db_connection):
        self.db = db_connection

    def check_access(
        self,
        user_id: int,
        resource_type: str,
        resource_id: int,
        action: str = "read",
    ) -> bool:

        sensitivity = self._get_resource_sensitivity(resource_type, resource_id)
        if sensitivity is None:
            logger.warning("Resource not found: %s #%d", resource_type, resource_id)
            return False

        has_access = self._evaluate_policies(user_id, resource_type, sensitivity, action)

        if has_access:
            if sensitivity in ("confidential", "restricted"):
                self.log_audit(
                    user_id=user_id, action="view", resource_type=resource_type,
                    resource_id=resource_id,
                    details=f"Accessed {sensitivity} {resource_type} #{resource_id}",
                )
            logger.info(
                "Access GRANTED: user=%d, %s #%d (%s), action=%s",
                user_id, resource_type, resource_id, sensitivity, action,
            )
        else:
            self.log_audit(
                user_id=user_id, action="access_denied", resource_type=resource_type,
                resource_id=resource_id,
                details=f"Denied {action} access to {sensitivity} {resource_type} #{resource_id}",
            )
            logger.warning(
                "Access DENIED: user=%d, %s #%d (%s), action=%s",
                user_id, resource_type, resource_id, sensitivity, action,
            )
        return has_access

    def check_policy_at_sensitivity(
        self,
        user_id: int,
        resource_type: str,
        sensitivity_level: str,
        action: str = "write",
    ) -> bool:
        try:
            with self.db.conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM omnigraph.user_roles ur
                        JOIN omnigraph.access_policies ap ON ur.role_id = ap.role_id
                        WHERE ur.user_id = %s AND ap.resource_type = %s
                          AND ap.sensitivity_level = %s
                          AND (
                              (%s = 'read'   AND ap.can_read = TRUE) OR
                              (%s = 'write'  AND ap.can_write = TRUE) OR
                              (%s = 'delete' AND ap.can_delete = TRUE)
                          )
                    )
                    """,
                    (user_id, resource_type, sensitivity_level, action, action, action),
                )
                return bool(cur.fetchone()[0])
        except psycopg2.Error as exc:
            logger.error("Policy-at-sensitivity check failed: %s", exc)
            return False

    def validate_permission(self, user_id: int, required_permission: str) -> bool:
        try:
            with self.db.conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT r.permissions FROM omnigraph.user_roles ur
                    JOIN omnigraph.roles r ON r.role_id = ur.role_id
                    WHERE ur.user_id = %s
                    """,
                    (user_id,),
                )
                for row in cur.fetchall():
                    permissions = row[0] if row[0] else []
                    if required_permission in permissions:
                        return True
            return False
        except psycopg2.Error as exc:
            logger.error("Permission validation failed: %s", exc)
            return False

    def get_user_roles(self, user_id: int) -> List[Dict]:
        try:
            with self.db.conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT r.role_id, r.role_name, r.description, r.permissions, ur.assigned_at
                    FROM omnigraph.user_roles ur
                    JOIN omnigraph.roles r ON r.role_id = ur.role_id
                    WHERE ur.user_id = %s ORDER BY r.role_name
                    """,
                    (user_id,),
                )
                columns = ["role_id", "role_name", "description", "permissions", "assigned_at"]
                return [dict(zip(columns, row)) for row in cur.fetchall()]
        except psycopg2.Error as exc:
            logger.error("Failed to get user roles: %s", exc)
            return []

    def get_user_access_matrix(self, user_id: int) -> List[Dict]:
        try:
            with self.db.conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT ap.resource_type, ap.sensitivity_level,
                           BOOL_OR(ap.can_read) AS can_read,
                           BOOL_OR(ap.can_write) AS can_write,
                           BOOL_OR(ap.can_delete) AS can_delete
                    FROM omnigraph.user_roles ur
                    JOIN omnigraph.access_policies ap ON ap.role_id = ur.role_id
                    WHERE ur.user_id = %s
                    GROUP BY ap.resource_type, ap.sensitivity_level
                    ORDER BY ap.resource_type, ap.sensitivity_level
                    """,
                    (user_id,),
                )
                columns = ["resource_type", "sensitivity_level", "can_read", "can_write", "can_delete"]
                return [dict(zip(columns, row)) for row in cur.fetchall()]
        except psycopg2.Error as exc:
            logger.error("Failed to get access matrix: %s", exc)
            return []

    def log_query(
        self,
        user_id: int,
        query_text: str,
        query_type: str,
        results_count: int = 0,
        execution_ms: int = 0,
    ) -> Optional[int]:
        try:
            with self.db.conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO omnigraph.query_logs
                        (user_id, query_text, query_type, results_count, execution_ms)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING log_id
                    """,
                    (user_id, query_text, query_type, results_count, execution_ms),
                )
                log_id = cur.fetchone()[0]
            self.db.conn.commit()
            return log_id
        except psycopg2.Error as exc:
            self.db.conn.rollback()
            logger.error("Failed to log query: %s", exc)
            return None

    def log_audit(
        self,
        user_id: int,
        action: str,
        resource_type: str,
        resource_id: Optional[int] = None,
        details: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> Optional[int]:
        try:
            with self.db.conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO omnigraph.audit_logs
                        (user_id, action, resource_type, resource_id, details, ip_address)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING audit_id
                    """,
                    (user_id, action, resource_type, resource_id, details, ip_address),
                )
                audit_id = cur.fetchone()[0]
            self.db.conn.commit()
            return audit_id
        except psycopg2.Error as exc:
            self.db.conn.rollback()
            logger.error("Failed to create audit log: %s", exc)
            return None

    def get_audit_trail(
        self,
        user_id: Optional[int] = None,
        resource_type: Optional[str] = None,
        action: Optional[str] = None,
        days: int = 30,
        limit: int = 50,
    ) -> List[Dict]:
        try:
            conditions = ["al.created_at >= %s"]
            params: list = [datetime.now() - timedelta(days=days)]
            if user_id:
                conditions.append("al.user_id = %s")
                params.append(user_id)
            if resource_type:
                conditions.append("al.resource_type = %s")
                params.append(resource_type)
            if action:
                conditions.append("al.action = %s")
                params.append(action)
            params.append(limit)
            where_clause = " AND ".join(conditions)

            with self.db.conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT al.audit_id, al.created_at, u.full_name, u.department,
                           al.action, al.resource_type, al.resource_id, al.details, al.ip_address
                    FROM omnigraph.audit_logs al
                    JOIN omnigraph.users u ON u.user_id = al.user_id
                    WHERE {where_clause}
                    ORDER BY al.created_at DESC
                    LIMIT %s
                    """,
                    params,
                )
                columns = ["audit_id", "timestamp", "user", "department",
                           "action", "resource_type", "resource_id", "details", "ip_address"]
                return [dict(zip(columns, row)) for row in cur.fetchall()]
        except psycopg2.Error as exc:
            logger.error("Audit trail retrieval failed: %s", exc)
            return []

    def get_sensitive_access_report(self, days: int = 30) -> List[Dict]:
        try:
            with self.db.conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT al.created_at, u.full_name, u.department,
                           STRING_AGG(DISTINCT r.role_name, ', ') AS roles,
                           al.action, d.title AS document_title, d.sensitivity_level,
                           al.details, al.ip_address
                    FROM omnigraph.audit_logs al
                    JOIN omnigraph.users u ON u.user_id = al.user_id
                    LEFT JOIN omnigraph.documents d ON d.document_id = al.resource_id
                    LEFT JOIN omnigraph.user_roles ur ON ur.user_id = al.user_id
                    LEFT JOIN omnigraph.roles r ON r.role_id = ur.role_id
                    WHERE al.resource_type = 'document'
                      AND d.sensitivity_level IN ('confidential', 'restricted')
                      AND al.created_at >= %s
                    GROUP BY al.audit_id, al.created_at, u.full_name, u.department,
                             al.action, d.title, d.sensitivity_level, al.details, al.ip_address
                    ORDER BY al.created_at DESC
                    """,
                    (datetime.now() - timedelta(days=days),),
                )
                columns = ["timestamp", "user", "department", "roles", "action",
                           "document", "sensitivity", "details", "ip_address"]
                return [dict(zip(columns, row)) for row in cur.fetchall()]
        except psycopg2.Error as exc:
            logger.error("Sensitive access report failed: %s", exc)
            return []

    def get_query_analytics(self, days: int = 30) -> Dict:
        try:
            since = datetime.now() - timedelta(days=days)
            with self.db.conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*), query_type,
                           ROUND(AVG(execution_ms)::NUMERIC, 1),
                           ROUND(AVG(results_count)::NUMERIC, 1)
                    FROM omnigraph.query_logs
                    WHERE created_at >= %s
                    GROUP BY query_type ORDER BY COUNT(*) DESC
                    """,
                    (since,),
                )
                by_type = [
                    {
                        "count": row[0],
                        "query_type": row[1],
                        "avg_execution_ms": float(row[2]) if row[2] else 0,
                        "avg_results": float(row[3]) if row[3] else 0,
                    }
                    for row in cur.fetchall()
                ]

                cur.execute(
                    """
                    SELECT u.full_name, COUNT(*) AS query_count
                    FROM omnigraph.query_logs ql
                    JOIN omnigraph.users u ON u.user_id = ql.user_id
                    WHERE ql.created_at >= %s
                    GROUP BY u.user_id, u.full_name
                    ORDER BY query_count DESC LIMIT 10
                    """,
                    (since,),
                )
                top_users = [{"user": r[0], "query_count": r[1]} for r in cur.fetchall()]

            return {"period_days": days, "by_type": by_type, "top_users": top_users}
        except psycopg2.Error as exc:
            logger.error("Query analytics failed: %s", exc)
            return {}

    def assign_role(self, user_id: int, role_id: int, assigned_by: int) -> bool:
        try:
            with self.db.conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO omnigraph.user_roles (user_id, role_id, assigned_by)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (user_id, role_id) DO NOTHING
                    """,
                    (user_id, role_id, assigned_by),
                )
            self.db.conn.commit()
            self.log_audit(
                user_id=assigned_by, action="update", resource_type="role",
                resource_id=role_id, details=f"Assigned role {role_id} to user {user_id}",
            )
            return True
        except psycopg2.Error as exc:
            self.db.conn.rollback()
            logger.error("Failed to assign role: %s", exc)
            return False

    def revoke_role(self, user_id: int, role_id: int, revoked_by: int) -> bool:
        try:
            with self.db.conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM omnigraph.user_roles WHERE user_id = %s AND role_id = %s",
                    (user_id, role_id),
                )
            self.db.conn.commit()
            self.log_audit(
                user_id=revoked_by, action="delete", resource_type="role",
                resource_id=role_id, details=f"Revoked role {role_id} from user {user_id}",
            )
            return True
        except psycopg2.Error as exc:
            self.db.conn.rollback()
            logger.error("Failed to revoke role: %s", exc)
            return False

    def filter_accessible_documents(
        self, user_id: int, doc_ids: List[int], action: str = "read",
    ) -> List[int]:
        if not doc_ids:
            return []
        try:
            with self.db.conn.cursor() as cur:
                cur.execute(
                    "SELECT document_id, sensitivity_level FROM omnigraph.documents "
                    "WHERE document_id = ANY(%s)",
                    (doc_ids,),
                )
                doc_sensitivity = dict(cur.fetchall())

                cur.execute(
                    """
                    SELECT DISTINCT ap.sensitivity_level
                    FROM omnigraph.user_roles ur
                    JOIN omnigraph.access_policies ap ON ur.role_id = ap.role_id
                    WHERE ur.user_id = %s AND ap.resource_type = 'document'
                      AND (
                          (%s = 'read'   AND ap.can_read = TRUE) OR
                          (%s = 'write'  AND ap.can_write = TRUE) OR
                          (%s = 'delete' AND ap.can_delete = TRUE)
                      )
                    """,
                    (user_id, action, action, action),
                )
                allowed = {row[0] for row in cur.fetchall()}

            return [d for d in doc_ids if doc_sensitivity.get(d) in allowed]
        except psycopg2.Error as exc:
            logger.error("Batch access filter failed: %s", exc)
            return []

    def _get_resource_sensitivity(self, resource_type: str, resource_id: int) -> Optional[str]:
        if resource_type != "document":
            return "public"
        try:
            with self.db.conn.cursor() as cur:
                cur.execute(
                    "SELECT sensitivity_level FROM omnigraph.documents WHERE document_id = %s",
                    (resource_id,),
                )
                row = cur.fetchone()
                return row[0] if row else None
        except psycopg2.Error as exc:
            logger.error("Failed to get resource sensitivity: %s", exc)
            return None

    def _evaluate_policies(
        self, user_id: int, resource_type: str, sensitivity: str, action: str,
    ) -> bool:
        try:
            with self.db.conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM omnigraph.user_roles ur
                        JOIN omnigraph.access_policies ap ON ur.role_id = ap.role_id
                        WHERE ur.user_id = %s AND ap.resource_type = %s
                          AND ap.sensitivity_level = %s
                          AND (
                              (%s = 'read'   AND ap.can_read = TRUE) OR
                              (%s = 'write'  AND ap.can_write = TRUE) OR
                              (%s = 'delete' AND ap.can_delete = TRUE)
                          )
                    )
                    """,
                    (user_id, resource_type, sensitivity, action, action, action),
                )
                return cur.fetchone()[0]
        except psycopg2.Error as exc:
            logger.error("Policy evaluation failed: %s", exc)
            return False


if __name__ == "__main__":
    try:
        from .ingestion_pipeline import DatabaseConnection
    except ImportError:
        from ingestion_pipeline import DatabaseConnection

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    db = DatabaseConnection()
    db.connect()
    acm = AccessControlManager(db)

    print("=== Access Control Checks ===")
    for uid, rtype, rid, action, desc in [
        (1, "document", 1, "read", "Admin → public doc"),
        (8, "document", 5, "read", "Consumer → restricted doc"),
        (5, "document", 5, "read", "Compliance → restricted doc"),
        (10, "document", 2, "write", "Consumer → confidential doc write"),
    ]:
        result = acm.check_access(uid, rtype, rid, action)
        print(f"  {'✓ GRANTED' if result else '✗ DENIED'}  {desc}")

    print("\n=== User Roles (id=1) ===")
    for r in acm.get_user_roles(1):
        print(f"  {r['role_name']}: {r['permissions']}")

    print("\n=== Access Matrix (id=8) ===")
    for m in acm.get_user_access_matrix(8):
        print(f"  {m['resource_type']}/{m['sensitivity_level']}: "
              f"R={m['can_read']} W={m['can_write']} D={m['can_delete']}")

    print("\n=== Recent Audit Trail ===")
    for entry in acm.get_audit_trail(days=365, limit=5):
        print(f"  [{entry['timestamp']}] {entry['user']}: {entry['action']} on {entry['resource_type']}")

    db.disconnect()
