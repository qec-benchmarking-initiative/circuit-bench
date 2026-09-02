import io
import tarfile
from pathlib import Path

import pytest

from registry.ecz.projection import (
    EczProjectionError,
    parse_archive,
    parse_source_directory,
    render_display_name,
)

FIXTURES = Path(__file__).parents[1] / "fixtures" / "eczoo"


def test_valid_source_directory_builds_complete_projection():
    projection = parse_source_directory(FIXTURES / "snapshot_a")

    assert [term.code_id for term in projection.terms] == [
        "planar",
        "root",
        "surface",
    ]
    assert projection.parent_edges == {
        ("planar", "surface"),
        ("surface", "root"),
    }
    assert projection.term_by_id["planar"].display_name == "Planar 2D code"


@pytest.mark.parametrize(
    ("fixture", "message"),
    [
        ("invalid_cycle", "cycle"),
        ("invalid_dangling_parent", "missing parent"),
        ("invalid_duplicate_id", "Duplicate ECZ code_id"),
        ("invalid_duplicate_yaml_key", "Duplicate YAML mapping key"),
    ],
)
def test_invalid_projection_is_rejected(fixture, message):
    with pytest.raises(EczProjectionError, match=message):
        parse_source_directory(FIXTURES / fixture)


def test_archive_reader_does_not_extract_and_rejects_links(tmp_path):
    archive_buffer = io.BytesIO()
    with tarfile.open(fileobj=archive_buffer, mode="w:gz") as archive:
        content = b"code_id: root\nname: Root code\n"
        member = tarfile.TarInfo("ecz/codes/root.yml")
        member.size = len(content)
        archive.addfile(member, io.BytesIO(content))
    projection = parse_archive(archive_buffer.getvalue())
    assert projection.terms[0].code_id == "root"
    assert list(tmp_path.iterdir()) == []

    link_buffer = io.BytesIO()
    with tarfile.open(fileobj=link_buffer, mode="w:gz") as archive:
        link = tarfile.TarInfo("ecz/codes/root.yml")
        link.type = tarfile.SYMTYPE
        link.linkname = "/etc/passwd"
        archive.addfile(link)
    with pytest.raises(EczProjectionError, match="link member"):
        parse_archive(link_buffer.getvalue())


def test_name_renderer_is_plain_text_and_preserves_unknown_commands():
    assert render_display_name(r"\(\mathbb{Z}_2\) \textit{surface} code") == (
        "Z_2 surface code"
    )
    assert render_display_name(r"<script>x</script> \mystery{code}") == (
        "<script>x</script> mysterycode"
    )
