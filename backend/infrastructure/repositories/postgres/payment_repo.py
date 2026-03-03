"""Payment validation repository."""

from __future__ import annotations

from backend.infrastructure.repositories.postgres.base import BasePostgresRepo


class PaymentRepo(BasePostgresRepo):

    def log_payment_validation(
        self, contractor_id: str, contractor_type: str,
        input_text: str, parsed_json: str,
        warnings: list[str] | None = None, is_final: bool = False,
    ) -> str:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO payment_validations
                   (contractor_id, contractor_type, input_text, parsed_json, validation_warnings, is_final)
                   VALUES (%s, %s, %s, %s, %s, %s)
                   RETURNING id""",
                (contractor_id, contractor_type, input_text, parsed_json, warnings or [], is_final),
            )
            return str(cur.fetchone()[0])

    def finalize_payment_validation(self, validation_id: str) -> None:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE payment_validations SET is_final = TRUE WHERE id = %s",
                (validation_id,),
            )
