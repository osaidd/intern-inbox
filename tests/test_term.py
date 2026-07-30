from career_hunt.term import term


def test_title_season_and_year():
    assert term("Software Engineering Intern (Summer 2027)") == "Summer 2027"
    assert term("Fall 2026 Intern, Brand Marketing") == "Fall 2026"
    assert term("2027 Winter Co-op — Winter 2027 start") == "Winter 2027"


def test_title_season_alone_is_enough():
    assert term("Summer Intern, Product") == "Summer"


def test_jd_needs_season_plus_year():
    # a dated season in the JD is a real term...
    assert term("Data Intern", "This is a Summer 2026 internship in NYC.") == "Summer 2026"
    # ...but a bare season in prose is noise ("join us in the fall")
    assert term("AI Intern", "You would join us in the fall to help ship.") is None


def test_spring_boot_never_matches():
    assert term("Java Spring Boot Intern") is None
    assert term("Intern", "Experience with Spring Framework required.") is None


def test_autumn_normalizes_and_none_is_safe():
    assert term("Autumn 2026 Intern") == "Fall 2026"
    assert term(None) is None
    assert term("", None) is None
