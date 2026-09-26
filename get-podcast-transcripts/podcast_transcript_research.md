# Notes de recherche — podcasts et transcriptions

## Exemple Podcast Addict

- URL : https://podcastaddict.com/encore-heureux/episode/223501658
- Podcast : **Encore heureux**
- Épisode : **« Qui aide les aidant•es ? »**
- Date : 9 mai 2026 ; durée affichée : 58 minutes.
- Le descriptif identifie l’éditeur : Binge (URBANIA Audio) et l’hébergement : Audiomeans.
- La page contient un lien de téléchargement temporairement signé (`/episode_download.php?token=…`), mais ne présente pas de transcript ni d’URL de site éditeur.
- Conclusion initiale : Podcast Addict est une bonne source de métadonnées et parfois d’audio, mais il faut retrouver le flux RSS / l’éditeur plutôt que compter sur la page seule pour une transcription.

## Sources utilisées

1. https://podcastaddict.com/encore-heureux/episode/223501658

## Exemple YouTube correspondant

La recherche relie le même épisode à la vidéo officielle de la chaîne Binge Audio : https://www.youtube.com/watch?v=-V_9fKvEkn0. Le titre est « Qui pour aider les aidant·es ? », la durée est de 55 min 32 s et la vidéo est identifiée comme appartenant à la playlist *Encore heureux*. La vidéo contient donc l’audio de l’épisode et complète l’information découverte depuis Podcast Addict.

Toutefois, l’interface visible de YouTube indique explicitement « Subtitles/closed captions unavailable ». Dans ce cas précis, YouTube ne fournit donc pas de transcript natif récupérable de manière fiable, même si cette voie reste à privilégier pour les autres vidéos où une piste de sous-titres ou de transcription existe.

La comparaison montre aussi une légère divergence de titre et de durée entre les plateformes (Podcast Addict : 58 min ; YouTube : 55:32). Toute automatisation devra conserver l’URL, le titre normalisé, la date, la durée et idéalement une empreinte audio afin d’éviter les mauvaises correspondances.

## Sources supplémentaires

2. https://www.youtube.com/watch?v=-V_9fKvEkn0
3. https://podcasts.apple.com/fr/podcast/qui-pour-aider-les-aidant-es/id1630399462?i=1000766624840

## Normes et sources de transcription vérifiées

La meilleure source automatisable est le flux RSS d’origine, avant la page de l’éditeur elle-même. Le standard `podcast:transcript`, placé dans l’élément d’épisode RSS, peut exposer une ou plusieurs transcriptions dans des formats exploitables tels que texte brut, HTML, VTT, JSON ou SRT. Il peut aussi préciser la langue et indiquer qu’il s’agit de sous-titres horodatés. Il faut donc systématiquement rechercher et analyser cette balise avant de tenter une reconnaissance vocale. [Podcast Namespace — transcript](https://podcasting2.org/docs/podcast-namespace/tags/transcript)

Apple Podcasts génère également des transcriptions pour un ensemble de langues comprenant le français et accepte les transcriptions propriétaires via le RSS. Ces transcriptions sont utiles pour la consultation dans l’application, mais Apple ne propose pas un mécanisme public documenté permettant de les exporter intégralement pour n’importe quel podcast. Elles ne doivent donc pas être la dépendance automatisée principale. [Apple — Transcripts on Apple Podcasts](https://podcasters.apple.com/support/5316-transcripts-on-apple-podcasts)

YouTube prend en charge les sous-titres automatiques en français, mais ils peuvent être absents, différés ou erronés, notamment lorsque l’audio est complexe, trop long, de mauvaise qualité ou comporte des locuteurs qui se chevauchent. Pour une vidéo donnée, l’existence d’une piste de sous-titres doit donc être testée, sans supposer qu’une vidéo YouTube garantit un transcript. L’exemple fourni illustre justement ce cas : la piste de sous-titres n’est pas disponible dans l’interface. [YouTube Help — Automatic captions](https://support.google.com/youtube/answer/6373554)

