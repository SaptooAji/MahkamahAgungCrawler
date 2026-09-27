from scraper.pagination import PaginationScraper


CURRENT_URL = (
    "https://putusan3.mahkamahagung.go.id/"
    "direktori/index/"
    "tahunjenis/putus/"
    "tahun/2021.html"
)


def main():
    total_pages = 499

    pages = PaginationScraper.build_page_descriptors(
        current_url=CURRENT_URL,
        total_pages=499,
        page_url_template=(
            "https://putusan3.mahkamahagung.go.id/"
            "direktori/index/"
            "tahunjenis/putus/"
            "tahun/2021/page/{page}.html"
        ),
    )

    print()
    print("=" * 70)
    print("BUILD PAGE DESCRIPTORS TEST")
    print("=" * 70)

    print(
        f"Total descriptors: {len(pages)}"
    )

    print()
    print("FIRST 5:")

    for page in pages[:5]:
        print(
            f"  page={page.page_number} "
            f"url={page.url_page}"
        )

    print()
    print("LAST 5:")

    for page in pages[-5:]:
        print(
            f"  page={page.page_number} "
            f"url={page.url_page}"
        )

    print()
    print("ASSERTIONS:")

    assert len(pages) == 499

    print(
        "TOTAL DESCRIPTORS = 499: PASS"
    )

    page_numbers = [
        page.page_number
        for page in pages
    ]

    assert page_numbers == list(
        range(1, 500)
    )

    print(
        "PAGE NUMBERS = 1..499: PASS"
    )

    assert (
        pages[0].page_number == 1
    )

    print(
        "FIRST PAGE NUMBER = 1: PASS"
    )

    assert (
        pages[0].url_page
        == CURRENT_URL
    )

    print(
        "PAGE 1 USES CANONICAL URL: PASS"
    )

    assert (
        "/page/1.html"
        not in pages[0].url_page
    )

    print(
        "PAGE 1 IS NOT /page/1.html: PASS"
    )

    assert (
        pages[1].page_number == 2
    )

    assert (
        pages[1].url_page.endswith(
            "/page/2.html"
        )
    )

    print(
        "PAGE 2 URL: PASS"
    )

    assert (
        pages[2].page_number == 3
    )

    assert (
        pages[2].url_page.endswith(
            "/page/3.html"
        )
    )

    print(
        "PAGE 3 URL: PASS"
    )

    assert (
        pages[3].page_number == 4
    )

    assert (
        pages[3].url_page.endswith(
            "/page/4.html"
        )
    )

    print(
        "PAGE 4 URL: PASS"
    )

    assert (
        pages[-1].page_number == 499
    )

    print(
        "LAST PAGE NUMBER = 499: PASS"
    )

    assert (
        pages[-1].url_page.endswith(
            "/page/499.html"
        )
    )

    print(
        "LAST PAGE URL: PASS"
    )

    assert not any(
        "/page/1.html"
        in page.url_page
        for page in pages
    )

    print(
        "NO /page/1.html EXISTS: PASS"
    )

    assert all(
        page.page_number == index
        for index, page
        in enumerate(pages, start=1)
    )

    print(
        "SEQUENTIAL PAGE NUMBERS: PASS"
    )

    print()
    print(
        "BUILD PAGE DESCRIPTORS TEST: PASS"
    )


if __name__ == "__main__":
    main()