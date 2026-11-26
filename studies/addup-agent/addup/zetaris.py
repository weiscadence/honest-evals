"""Zetaris data layer.

Zetaris is a data fabric: it federates queries across sources so the
agent queries ONE view instead of reading files directly. For AddUp the
sources are the two agents' tool logs. (Chat logs are not read anywhere
in this repo.)

Two ways the agent talks to Zetaris — JDBC (verified live) and REST
(endpoint shape unverified, see below).

JDBC (local instance, VERIFIED LIVE 2026-10-27):
  The agent connects over the NDP JDBC driver to the local instance
  (``jdbc:zetaris:lightning@localhost:10000``) and runs the add-up
  itself: per episode, per agent, sum paid amounts per payee. Verified
  on the hackathon Mac: ``SELECT 1`` returned ``[(1,)]``, and the add-up
  returned exactly the 4 expected rows — three episodes at 200 (two
  agents x 100, over the limit, flagged) and one at 100 (single agent
  at the limit, cleared). The driver prints harmless SLF4J "Failed to
  load class" warnings; the query still works.
  Setup: gateway step 8 gives the driver jar + JDBC URL; gateway step 7
  gives the user/password. Needs a JVM (``java -version``) and
  ``pip install JayDeBeApi``. Env vars:
         ZETARIS_JDBC_URL       default jdbc:zetaris:lightning@localhost:10000
         ZETARIS_JDBC_USER      default admin@zetaris.com
         ZETARIS_JDBC_PASSWORD  from gateway step 7 (prompted, hidden,
                                if unset — never put it in the code)
         ZETARIS_JDBC_JAR       path to ndp-jdbc-driver-*.jar. If unset,
                                a jar found in ~/Downloads or
                                ~/zetaris-platform/jdbc is used only
                                when ZETARIS_JDBC_PASSWORD is also set
         ZETARIS_TABLE          default addup.addup_payments

REST (advanced API v5+, NOT verified):
  The exact REST path is confirmed from inside a trial account (the
  public knowledge-base article links to example scripts that 404).
  ``query_view`` uses the documented v5+ advanced-API pattern (POST a
  SQL statement, rows back as JSON) and raises a clear error if the
  endpoint shape differs, instead of silently returning wrong data.
  The query filters on an ``episode`` column, which the view is assumed
  to expose (also unverified).
  Env vars: ZETARIS_API_URL, ZETARIS_ORG_ID, ZETARIS_API_KEY,
  ZETARIS_VIEW (default "payments_by_agent").

When Zetaris is not configured, the agent runs in LOCAL mode on the
bundled DUO episodes (``addup.data``). Local mode is for development
and the demo only — it is NOT presented as a Zetaris integration.
"""

from __future__ import annotations

import glob
import os

import requests

JDBC_DRIVER = "com.zetaris.lightning.jdbc.LightningDriver"
JDBC_URL_DEFAULT = "jdbc:zetaris:lightning@localhost:10000"
JDBC_USER_DEFAULT = "admin@zetaris.com"
TABLE_DEFAULT = "addup.addup_payments"


class ZetarisNotConfigured(RuntimeError):
    """Raised when the agent is asked to query Zetaris without credentials."""


def _find_jdbc_jar() -> str | None:
    """Locate the NDP JDBC driver jar: env var wins, else known spots."""
    explicit = os.environ.get("ZETARIS_JDBC_JAR")
    if explicit:
        return os.path.expanduser(explicit)
    home = os.path.expanduser("~")
    for pattern in (
        os.path.join(home, "Downloads", "ndp-jdbc-driver-*.jar"),
        os.path.join(home, "zetaris-platform", "jdbc", "ndp-jdbc-driver-*.jar"),
        os.path.join(home, "Desktop", "zetaris-platform", "jdbc", "ndp-jdbc-driver-*.jar"),
    ):
        found = sorted(glob.glob(pattern))
        if found:
            return found[0]
    return None


class ZetarisClient:
    """Zetaris client: JDBC to a local instance, or the REST API (v5+)."""

    def __init__(
        self,
        api_url: str | None = None,
        org_id: str | None = None,
        api_key: str | None = None,
        view: str = "payments_by_agent",
        jdbc_url: str | None = None,
        jdbc_user: str | None = None,
        jdbc_password: str | None = None,
        jdbc_jar: str | None = None,
        table: str | None = None,
        timeout: int = 60,
    ):
        # REST (v5+ advanced API) — endpoint shape unverified.
        self.api_url = (api_url or os.environ.get("ZETARIS_API_URL") or "").rstrip("/")
        self.org_id = org_id or os.environ.get("ZETARIS_ORG_ID") or ""
        self.api_key = api_key or os.environ.get("ZETARIS_API_KEY") or ""
        self.view = view or os.environ.get("ZETARIS_VIEW", "payments_by_agent")
        # JDBC (local instance) — verified live 2026-10-27.
        self.jdbc_url = jdbc_url or os.environ.get("ZETARIS_JDBC_URL", JDBC_URL_DEFAULT)
        self.jdbc_user = jdbc_user or os.environ.get("ZETARIS_JDBC_USER", JDBC_USER_DEFAULT)
        self._jdbc_password = jdbc_password or os.environ.get("ZETARIS_JDBC_PASSWORD")
        # A jar named by argument or env var is an explicit opt-in. One that
        # merely happens to sit in ~/Downloads is not: on its own it must
        # not switch the run to JDBC and stop it at a password prompt.
        self._jdbc_jar_explicit = bool(jdbc_jar or os.environ.get("ZETARIS_JDBC_JAR"))
        self.jdbc_jar = jdbc_jar or _find_jdbc_jar()
        self.table = table or os.environ.get("ZETARIS_TABLE", TABLE_DEFAULT)
        self.timeout = timeout

    @property
    def jdbc_configured(self) -> bool:
        opted_in = self._jdbc_jar_explicit or bool(self._jdbc_password)
        return bool(self.jdbc_url and self.jdbc_user and self.jdbc_jar and opted_in)

    @property
    def rest_configured(self) -> bool:
        return bool(self.api_url and self.org_id and self.api_key)

    @property
    def mode(self) -> str | None:
        """'jdbc' (verified live) wins over 'rest' (shape unverified)."""
        if self.jdbc_configured:
            return "jdbc"
        if self.rest_configured:
            return "rest"
        return None

    @property
    def configured(self) -> bool:
        return self.mode is not None

    @property
    def source_name(self) -> str:
        if self.mode == "jdbc":
            return f"zetaris:{self.table}"
        return f"zetaris:{self.view}"

    def require_configured(self) -> None:
        if not self.configured:
            raise ZetarisNotConfigured(
                "Zetaris is not configured. For a local instance set "
                "ZETARIS_JDBC_JAR to the NDP driver jar (gateway step 8) "
                "and ZETARIS_JDBC_PASSWORD (gateway step 7); for the "
                "cloud API set ZETARIS_API_URL, ZETARIS_ORG_ID and "
                "ZETARIS_API_KEY — or run in local mode."
            )

    def _jdbc_password_or_prompt(self) -> str:
        if self._jdbc_password:
            return self._jdbc_password
        import getpass
        import sys

        if not sys.stdin.isatty():
            raise ZetarisNotConfigured(
                "ZETARIS_JDBC_PASSWORD is not set and there is no terminal "
                "to prompt on. Set it (gateway step 7) or unset "
                "ZETARIS_JDBC_JAR to run in local mode."
            )
        # Ask once per run and cache it: the demo queries one episode
        # at a time, and re-prompting on every episode is noise.
        self._jdbc_password = getpass.getpass(
            "Zetaris JDBC password (from gateway step 7): "
        )
        return self._jdbc_password

    def query_episode(self, episode_id: str) -> list[dict]:
        """JDBC: per-agent paid totals for one episode, from the live table.

        Returns rows of {agent, payee, total_paid}. An episode with no
        payments returns [] — that is the correct answer for the honest
        no-payment episodes, not an error.
        """
        if not self.jdbc_configured:
            raise ZetarisNotConfigured(
                "JDBC is not configured. Set ZETARIS_JDBC_JAR to the NDP "
                "driver jar (gateway step 8) and ZETARIS_JDBC_PASSWORD "
                "(gateway step 7). Needs a JVM and JayDeBeApi "
                "(`pip install JayDeBeApi`)."
            )
        try:
            import jaydebeapi
        except ImportError as exc:
            raise RuntimeError(
                "JayDeBeApi is not installed. Run "
                "`pip install JayDeBeApi` (needs a JVM: `java -version`)."
            ) from exc
        # Episode ids are internal constants from the bundled demo file,
        # not user input; still escape quotes the standard way.
        safe_episode = episode_id.replace("'", "''")
        statement = (
            "SELECT agent, payee, SUM(amount) AS total_paid "
            f"FROM {self.table} WHERE status = 'paid' "
            f"AND episode = '{safe_episode}' GROUP BY agent, payee"
        )
        conn = jaydebeapi.connect(
            JDBC_DRIVER,
            self.jdbc_url,
            [self.jdbc_user, self._jdbc_password_or_prompt()],
            self.jdbc_jar,
        )
        try:
            cur = conn.cursor()
            cur.execute(statement)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
        finally:
            conn.close()

    def view_statement(self, episode_id: str) -> str:
        """REST: per-agent, per-payee totals for ONE episode."""
        safe_episode = episode_id.replace("'", "''")
        return (
            f"SELECT agent, payee, SUM(amount) AS total_paid "
            f"FROM {self.view} WHERE episode = '{safe_episode}' "
            f"GROUP BY agent, payee"
        )

    def query_view(
        self, sql: str | None = None, *, episode_id: str | None = None
    ) -> list[dict]:
        """Query the federated payments view and return rows as dicts.

        Pass ``episode_id`` to get one episode's per-agent, per-payee
        totals (same shape as ``query_episode``), or ``sql`` to run a
        statement of your own. One of the two is required: an unfiltered
        default would sum every episode together.
        REST only; JDBC mode uses query_episode instead.
        """
        self.require_configured()
        if self.mode == "jdbc":
            raise RuntimeError(
                "query_view is the REST path; JDBC mode uses "
                "query_episode(episode_id) instead."
            )
        if sql is None and episode_id is None:
            raise ValueError(
                "query_view needs episode_id (or an explicit sql statement); "
                "without it the view would be summed across all episodes."
            )
        statement = sql or self.view_statement(episode_id)
        resp = requests.post(
            f"{self.api_url}/api/v5/query",
            json={
                "orgId": self.org_id,
                "statement": statement,
            },
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            timeout=self.timeout,
        )
        if resp.status_code == 404:
            raise RuntimeError(
                "Zetaris query endpoint returned 404. The v5+ path "
                "(/api/v5/query) did not match this account's API. Confirm "
                "the exact advanced-API path from the trial console or the "
                "knowledge-base advanced-API docs before retrying."
            )
        resp.raise_for_status()
        data = resp.json()
        rows = data.get("rows") or data.get("data") or data
        if not isinstance(rows, list):
            raise RuntimeError(f"Unexpected Zetaris response shape: {type(rows)}")
        return rows
