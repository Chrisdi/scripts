from podcast_resolver import Episode, TranscriptAsset, choose_language, choose_rss_episode, youtube_video_id


assert youtube_video_id("https://youtu.be/-V_9fKvEkn0") == "-V_9fKvEkn0"

assets = [
    TranscriptAsset(url="https://example.test/en.vtt", mime_type="text/vtt", language="en"),
    TranscriptAsset(url="https://example.test/fr.html", mime_type="text/html", language="fr"),
]
assert choose_language(assets, "fr").url.endswith("fr.html")

input_episode = Episode(title="Qui aide les aidant es", podcast_name="Encore heureux", duration_seconds=3400)
rss_episode = Episode(title="Qui pour aider les aidant es", podcast_name="Encore heureux", duration_seconds=3332)
matched, score = choose_rss_episode(input_episode, [rss_episode])
assert matched is rss_episode
assert score > 0.45

print("Smoke test passed")
