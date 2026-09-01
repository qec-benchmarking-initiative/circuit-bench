from pathlib import Path


def test_shared_shell_exposes_the_seven_theme_mouse_control(client):
    response = client.get("/")
    content = response.content.decode()

    assert response.status_code == 200
    assert "css/themes.css" in content
    assert "js/theme-switcher.js" in content
    assert 'class="theme-switcher"' in content
    assert 'aria-hidden="true"' in content
    assert content.count("data-theme-swatch=") == 7
    assert "selected values shown in green" not in content
    assert (
        "<button"
        not in content.split('class="theme-switcher"', 1)[1].split("</div>", 1)[0]
    )


def test_two_theme_palettes_are_dark_modes():
    themes_css = (
        Path(__file__).resolve().parents[1] / "static" / "css" / "themes.css"
    ).read_text()

    assert themes_css.count("color-scheme: dark;") == 2
