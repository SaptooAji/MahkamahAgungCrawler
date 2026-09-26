from scraper.discovery_page import discover_page


def main():
    tahun = 2021

    url_page = (
        "https://putusan3.mahkamahagung.go.id/"
        f"direktori/index/tahunjenis/putus/"
        f"tahun/{tahun}.html"
    )

    print("=" * 70)
    print("TEST DISCOVERY SATU HALAMAN")
    print("=" * 70)

    results = discover_page(url_page)

    unpublish_items = [
        item
        for item in results
        if item["is_unpublish"]
    ]

    print()
    print(
        f"TOTAL HASIL DISCOVERY : {len(results)}"
    )

    print(
        f"TOTAL UNPUBLISH       : "
        f"{len(unpublish_items)}"
    )

    print()
    print("-" * 70)
    print("DATA UNPUBLISH")
    print("-" * 70)

    for index, item in enumerate(
        unpublish_items,
        start=1,
    ):
        print()
        print(f"[UNPUBLISH {index}]")
        print(f"Judul      : {item['judul']}")
        print(
            f"URL Detail : {item['url_detail']}"
        )

    print()
    print("-" * 70)
    print("10 DATA PERTAMA")
    print("-" * 70)

    for index, item in enumerate(
        results[:10],
        start=1,
    ):
        print()
        print(f"[{index}]")
        print(f"Judul       : {item['judul']}")
        print(
            f"URL Detail  : {item['url_detail']}"
        )
        print(
            f"Unpublish   : {item['is_unpublish']}"
        )

    print()
    print("=" * 70)
    print("TEST DISCOVERY SELESAI")
    print("=" * 70)


if __name__ == "__main__":
    main()