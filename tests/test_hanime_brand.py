from app.services.hentai_playlist import _hanime_brand_records, _hanime_records


def test_hanime_brand_embedded_records_are_parsed():
    page = (
        'name:"Example 1",slug:"example-1",created_at:"x",'
        'poster_url:"https:\\u002F\\u002Fcdn.example\\u002Fposter.jpg",'
        'cover_url:"x",duration_in_ms:125000'
    )

    records = _hanime_brand_records(page)

    assert records == [
        (
            "https://hanime.tv/videos/hentai/example-1",
            "Example 1",
            "https://cdn.example/poster.jpg",
            125,
        )
    ]


def test_hanime_playlist_dom_records_fill_embedded_gaps():
    page = """
    <div class="video__item">
      <a href="/videos/hentai/example-1?playlist_id=abc">
        <div class="video__item__image" style="background:transparent url(https://cdn.example/example-1.jpg) center"></div>
        <span class="video__item__name">Example 1</span>
      </a>
    </div>
    <div class="video__item">
      <a href="/videos/hentai/example-2?playlist_id=abc">
        <div class="video__item__image" style="background:transparent url(https://cdn.example/example-2.jpg) center"></div>
        <span class="video__item__name">Example 2</span>
      </a>
    </div>
    name:"Example 1",slug:"example-1",poster_url:"https:\\u002F\\u002Fcdn.example\\u002Fbetter.jpg",duration_in_ms:125000
    """

    records = _hanime_records(page, "https://hanime.tv/playlists/abc")

    assert records == [
        (
            "https://hanime.tv/videos/hentai/example-1",
            "Example 1",
            "https://cdn.example/better.jpg",
            125,
        ),
        (
            "https://hanime.tv/videos/hentai/example-2",
            "Example 2",
            "https://cdn.example/example-2.jpg",
            None,
        ),
    ]
