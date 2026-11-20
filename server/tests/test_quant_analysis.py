"""Search provenance and honest reporting when complete annual data is unavailable."""

from app.llm.chatgpt import search_metadata


def test_search_sources_are_provider_observed_and_no_pages_are_retained():
    response = dict(
        output=[
            dict(
                type="web_search_call",
                status="completed",
                action=dict(
                    sources=[
                        dict(
                            url="https://example.com/prices",
                            title="Prices",
                            text="raw page content",
                        ),
                        dict(url="https://example.com/prices", title="Prices"),
                        dict(url="javascript:alert(1)", title="unsafe"),
                        dict(url="https://user:secret@example.com/private", title="unsafe"),
                    ]
                ),
            ),
            dict(
                type="message",
                content=[
                    dict(
                        annotations=[
                            dict(
                                type="url_citation",
                                url="https://example.com/filing",
                                title="Filing",
                            ),
                        ]
                    )
                ],
            ),
        ]
    )
    metadata = search_metadata(response)
    assert metadata["used"] and metadata["completed_calls"] == 1
    assert {s["url"] for s in metadata["sources"]} == {
        "https://example.com/prices",
        "https://example.com/filing",
    }
    assert all(set(s) == {"url", "title"} for s in metadata["sources"])


def test_prose_claim_or_incomplete_search_does_not_count_as_search():
    assert not search_metadata(
        dict(
            output=[
                dict(type="message", content=[dict(text="I searched a year of prices")]),
                dict(type="web_search_call", status="in_progress", action={}),
            ]
        )
    )["used"]


def test_web_citations_become_clickable_only_for_provider_observed_urls():
    from app.llm.chatgpt import web_report_text

    marker = "\ue200cite\ue202turn0search0\ue201"
    text = "공식 자료입니다. " + marker
    response = dict(
        output=[
            dict(
                type="message",
                content=[
                    dict(
                        type="output_text",
                        text=text,
                        annotations=[
                            dict(
                                type="url_citation",
                                url="https://example.com/filing",
                                start_index=len("공식 자료입니다. "),
                                end_index=len(text),
                            )
                        ],
                    )
                ],
            )
        ]
    )
    report = web_report_text(response, {"sources": [{"url": "https://example.com/filing"}]})
    assert "[출처](https://example.com/filing)" in report
    assert "turn0search0" not in report
    unverified = web_report_text(response, {"sources": []})
    assert "https://" not in unverified and "turn0search0" not in unverified
