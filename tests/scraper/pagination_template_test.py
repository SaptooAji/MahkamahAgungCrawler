from scraper.pagination import PaginationScraper


def main():
    page_2_url = (
        "https://putusan3.mahkamahagung.go.id/"
        "direktori/index/"
        "tahunjenis/putus/"
        "tahun/2021/page/2.html"
    )

    page_3_url = (
        "https://putusan3.mahkamahagung.go.id/"
        "direktori/index/"
        "tahunjenis/putus/"
        "tahun/2021/page/3.html"
    )

    print()
    print("=" * 70)
    print("PAGINATION URL TEMPLATE TEST")
    print("=" * 70)

    template = (
        PaginationScraper._derive_page_url_template(
            page_2_url=page_2_url,
            page_3_url=page_3_url,
        )
    )

    print(
        f"Template:\n{template}"
    )

    expected_template = (
        "https://putusan3.mahkamahagung.go.id/"
        "direktori/index/"
        "tahunjenis/putus/"
        "tahun/2021/page/{page}.html"
    )

    print()
    print("ASSERTIONS:")

    assert template == expected_template

    print(
        "PAGE 2 URL → TEMPLATE: PASS"
    )

    pages = (
        PaginationScraper.build_page_descriptors(
            current_url=(
                "https://putusan3.mahkamahagung.go.id/"
                "direktori/index/"
                "tahunjenis/putus/"
                "tahun/2021.html"
            ),
            total_pages=499,
            page_url_template=template,
        )
    )

    assert len(pages) == 499

    print(
        "TOTAL DESCRIPTORS = 499: PASS"
    )

    assert (
        pages[0].url_page
        == (
            "https://putusan3.mahkamahagung.go.id/"
            "direktori/index/"
            "tahunjenis/putus/"
            "tahun/2021.html"
        )
    )

    print(
        "PAGE 1 CANONICAL URL: PASS"
    )

    assert (
        pages[1].url_page
        == (
            "https://putusan3.mahkamahagung.go.id/"
            "direktori/index/"
            "tahunjenis/putus/"
            "tahun/2021/page/2.html"
        )
    )

    print(
        "PAGE 2 URL: PASS"
    )

    assert (
        pages[498].url_page
        == (
            "https://putusan3.mahkamahagung.go.id/"
            "direktori/index/"
            "tahunjenis/putus/"
            "tahun/2021/page/499.html"
        )
    )

    print(
        "PAGE 499 URL: PASS"
    )

    assert not any(
        "/page/1.html"
        in page.url_page
        for page in pages
    )

    print(
        "NO /page/1.html: PASS"
    )

    print()
    print(
        "PAGINATION URL TEMPLATE TEST: PASS"
    )


if __name__ == "__main__":
    main()