import io
import zipfile

from PIL import Image

from im_looking_for import extract


def test_chunks_cover_text_with_overlap_and_cut_at_boundaries():
    paragraph = "고양이가 창가에 앉아 있다. " * 30
    text = "\n\n".join([paragraph] * 6)
    pieces = extract.chunks(text, 1000, 150)
    assert len(pieces) > 1
    assert all(len(p) <= 1000 for p in pieces)
    assert all(p.endswith(".") for p in pieces[:-1])  # cut after a sentence, not inside a word
    joined = " ".join(pieces)
    assert "창가에" in joined
    # consecutive pieces share some text
    assert pieces[0][-40:].split()[-1] in pieces[1]


def test_chunks_empty_and_short():
    assert extract.chunks("  \n\n ", 100, 10) == []
    assert extract.chunks("hello", 100, 10) == ["hello"]


def test_chunks_long_unbroken_text_terminates():
    pieces = extract.chunks("x" * 5000, 1000, 200)
    assert sum(len(p) for p in pieces) >= 5000
    assert len(pieces) < 10


def test_decode_text_korean_legacy_encoding():
    assert extract.decode_text("한글 메모".encode("cp949")) == "한글 메모"
    assert extract.decode_text("\ufeffBOM".encode("utf-8")) == "BOM"
    assert extract.decode_text("utf16".encode("utf-16")) == "utf16"


def test_office_text_docx(tmp_path):
    path = tmp_path / "a.docx"
    xml = ('<w:document><w:body><w:p><w:r><w:t>첫 문단</w:t></w:r></w:p>'
           '<w:p><w:r><w:t>Second &amp; last</w:t></w:r></w:p></w:body></w:document>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", xml)
    assert extract.office_text(path).split("\n")[:2] == ["첫 문단", "Second & last"]


def test_read_doc_makes_prompted_chunks(tmp_path):
    path = tmp_path / "recipe.txt"
    path.write_text("김치찌개 끓이는 법", encoding="utf-8")
    (segment,) = extract.read_doc(path, extract.Options())
    assert segment.kind == "chunk" and segment.modality == "text"
    assert segment.prompt == "title: recipe | text: 김치찌개 끓이는 법"


def test_read_image_skips_icons_and_reencodes(tmp_path):
    Image.new("RGB", (64, 64), "red").save(tmp_path / "icon.png")
    Image.new("RGBA", (3000, 1500), (0, 0, 255, 128)).save(tmp_path / "big.png")
    assert list(extract.read_image(tmp_path / "icon.png", extract.Options())) == []
    (segment,) = extract.read_image(tmp_path / "big.png", extract.Options())
    picture = Image.open(io.BytesIO(segment.data))
    assert picture.format == "JPEG" and max(picture.size) == 1024


def test_read_pdf_renders_a_page_without_text(tmp_path):
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument.new()
    document.new_page(300, 400)
    document.save(tmp_path / "scan.pdf")
    document.close()
    (segment,) = extract.read_pdf(tmp_path / "scan.pdf", extract.Options())
    assert segment.kind == "page_image" and segment.loc == 1
    assert Image.open(io.BytesIO(segment.data)).size[1] == 1024
