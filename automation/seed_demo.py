"""Demo data for the README GIF: 15 invented companies, no real people or
listings. REFUSES to run on a database that already has rows — run it inside a
scratch clone, never your real checkout."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import db  # noqa: E402

ROWS = [
    # company, stage, headcount, area, role, priority, salary
    ("Loomcraft AI", "seed", 18, "SoHo", "AI Engineering Intern", "high", "$28-35/hr"),
    ("Fernwave", "series a", 42, "Flatiron", "Software Engineering Intern", "high", "$30/hr"),
    ("Copperline Labs", "seed", 11, "Dumbo", "Founders Associate Intern", "high", None),
    ("Quartz & Vine", "pre-seed", 6, "Williamsburg", "Growth Intern", "medium", None),
    ("Halyard Health AI", "series a", 55, "Union Square", "Product Management Intern", "high", "$32/hr"),
    ("Mosslight", "seed", 23, "Greenpoint", "Data Science Intern", "medium", "$26/hr"),
    ("Petrel Systems", "series b", 48, "FiDi", "Backend Engineering Intern", "medium", "$33/hr"),
    ("Juniper Yard", "seed", 15, "Long Island City", "BizOps Intern", "medium", None),
    ("Arcline Robotics", "series a", 61, "Brooklyn Navy Yard", "Robotics Software Intern", "medium", "$31/hr"),
    ("Novabranch", "seed", 9, "NoMad", "Full Stack Intern", "high", "$29/hr"),
    ("Tidegate Capital", "seed", 19, "Tribeca", "Fintech Product Intern", "medium", None),
    ("Emberfold", "pre-seed", 4, "East Village", "GTM Engineering Intern", "medium", None),
    ("Skylark Bio", "series a", 70, "Hudson Yards", "Data Engineering Intern", "low", "$27/hr"),
    ("Paperbark", "seed", 27, "Chelsea", "Product Design Intern", "low", None),
    ("Windrose Metrics", "series a", 38, "Midtown", "Analytics Intern", "medium", "$25/hr"),
]


def seed() -> int:
    conn = db.connect_ro() if db.DB_PATH.exists() else None
    if conn is not None:
        n = conn.execute("SELECT COUNT(*) c FROM opportunities").fetchone()["c"]
        conn.close()
        if n:
            raise SystemExit(f"refusing: database already has {n} opportunities "
                             "(run this in a scratch clone, not your real inbox)")
    for i, (co, stage, hc, area, role, pri, salary) in enumerate(ROWS, 1):
        cid = db.insert("companies", {
            "name": co, "name_key": co.lower(), "stage": stage, "headcount": hc,
            "enrich_status": "ok", "office_area": area})
        db.insert("opportunities", {
            "source": "ashby" if i % 3 else "github", "company": co, "role": role,
            "url": f"https://example.com/jobs/{i}", "location": "New York, NY",
            "status": "new", "priority": pri, "company_id": cid,
            "office_area": area, "work_mode": "hybrid" if i % 2 else "onsite",
            "salary_text": salary, "dedupe_hash": f"demo-{i}",
            "jd_text": f"{co} is hiring a {role.lower()} in {area}. Invented demo listing."})
    return len(ROWS)


if __name__ == "__main__":
    db.migrate()
    print(f"seeded {seed()} demo rows into {db.DB_PATH}")
