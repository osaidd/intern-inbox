# career_hunt/config.py
"""Load the career config into typed dataclasses. The personal config/career.toml
wins when it exists; a fresh clone falls back to the tracked example. No defaults
hide a bad file: missing keys raise KeyError with the key name, which is the
correct failure."""
import tomllib
from dataclasses import dataclass
from pathlib import Path

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
USER_PATH = CONFIG_DIR / "career.toml"
EXAMPLE_PATH = CONFIG_DIR / "career.example.toml"
DEFAULT_PATH = EXAMPLE_PATH  # kept for copied tests that pass load(DEFAULT_PATH)


@dataclass
class CompanyRules:
    tier1_stages: list
    tier1_max_headcount: int
    tier2_stages: list
    tier2_max_headcount: int
    hard_cap_headcount: int
    allow_late_stages: bool = False   # optional key: late-stage cos pass to tier logic


@dataclass
class EmailConfig:
    enabled: bool
    to: str
    smtp_host: str
    smtp_port: int
    smtp_user: str


@dataclass
class MailSource:
    """One extra job-alert sender parsed by the mail feed."""
    enabled: bool
    sender: str


@dataclass
class MailSources:
    builtin: MailSource
    wellfound: MailSource


@dataclass
class Config:
    allow_remote: bool
    interns_only: bool
    company: CompanyRules
    location_tier1: list
    location_tier2: list
    profile_keywords: list
    exclude_keywords: list
    exclude_companies: list
    size_red_flags: list
    target_titles: list
    github_urls: list
    linkedin_sender: str
    linkedin_lookback_days: int
    mail_sources: MailSources
    email: EmailConfig
    # [mail_scan] and [mail] are OPTIONAL (allow_late_stages precedent):
    # existing personal career.toml files must keep loading without them.
    mail_scan_enabled: bool = True
    mail_scan_lookback_days: int = 30
    mail_provider: str = "gmail"       # gmail | outlook | imap
    mail_imap_host: str = ""           # provider "imap" only (or CAREER_IMAP_HOST)
    outlook_client_id: str = ""        # Azure public-client app id (or OUTLOOK_CLIENT_ID)


def load(path=None) -> Config:
    if path is None:
        path = USER_PATH if USER_PATH.exists() else EXAMPLE_PATH
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    c, r, e, ms = raw["company"], raw["role"], raw["email"], raw["mail_sources"]
    return Config(
        allow_remote=raw["hunt"]["allow_remote"],
        interns_only=raw["hunt"]["interns_only"],
        company=CompanyRules(
            tier1_stages=[s.lower() for s in c["tier1_stages"]],
            tier1_max_headcount=c["tier1_max_headcount"],
            tier2_stages=[s.lower() for s in c["tier2_stages"]],
            tier2_max_headcount=c["tier2_max_headcount"],
            hard_cap_headcount=c["hard_cap_headcount"],
            allow_late_stages=c.get("allow_late_stages", False)),
        location_tier1=[a.lower() for a in raw["location"]["tier1"]],
        location_tier2=[a.lower() for a in raw["location"]["tier2"]],
        profile_keywords=r["profile_keywords"],
        exclude_keywords=r["exclude_keywords"],
        exclude_companies=r["exclude_companies"],
        size_red_flags=r["size_red_flags"],
        target_titles=r["target_titles"],
        github_urls=raw["github_intern"]["urls"],
        linkedin_sender=raw["linkedin_mail"]["sender"],
        linkedin_lookback_days=raw["linkedin_mail"]["lookback_days"],
        mail_sources=MailSources(
            builtin=MailSource(enabled=ms["builtin_enabled"], sender=ms["builtin_sender"]),
            wellfound=MailSource(enabled=ms["wellfound_enabled"],
                                 sender=ms["wellfound_sender"])),
        email=EmailConfig(enabled=e["enabled"], to=e["to"], smtp_host=e["smtp_host"],
                          smtp_port=e["smtp_port"], smtp_user=e["smtp_user"]),
        mail_scan_enabled=raw.get("mail_scan", {}).get("enabled", True),
        mail_scan_lookback_days=raw.get("mail_scan", {}).get("lookback_days", 30),
        mail_provider=raw.get("mail", {}).get("provider", "gmail"),
        mail_imap_host=raw.get("mail", {}).get("imap_host", ""),
        outlook_client_id=raw.get("mail", {}).get("outlook_client_id", ""),
    )


def user_agent(cfg: Config) -> dict:
    """Honest User-Agent for every outbound fetch — free APIs (Nominatim, boards)
    expect a contact address, so it comes from the user's own config."""
    contact = cfg.email.to or "set-your-email-in-config"
    return {"User-Agent": f"intern-inbox (personal internship search; contact: {contact})"}
