# 公開前チェックリスト

公開直前に、以下をすべて埋めること。埋め忘れは `grep -rn "____" .` で検出できる。

## 必須

- [ ] `LICENSE` の `YOUR-NAME-OR-HANDLE` を実名またはハンドルへ
- [ ] `docs/sources.md` の閲覧日（`____年__月__日`）をすべて記入
- [ ] `data/raw/CHECKSUMS.md` の取得日を記入
- [ ] `article/note_draft.md` の GitHub URL プレースホルダを実 URL へ
- [ ] 山梨県オープンデータ利用規約の最新本文を確認
  <https://www.pref.yamanashi.jp/opendata/kiyaku.html>
- [ ] e-Stat 利用規約を確認 <https://www.e-stat.go.jp/terms-of-use>

## 検証

- [ ] `cd code && python 01_parse_tokuyo.py && python 02_descriptives.py &&
      python 03_firststage_timber.py && python 04_matsutake_diagnostic.py`
      がすべてエラーなく完走する
- [ ] `data/raw/CHECKSUMS.md` の SHA-256 と実ファイルが一致する
      （`shasum -a 256 data/raw/*.xls` で照合）
- [ ] `output/figures/` の 3 枚に日本語が正しく表示されている（豆腐でない）
- [ ] `grep -rn "____" .` が空になる

## 推奨

- [ ] GitHub Release `v1.0.0` を作成
- [ ] Zenodo 連携で DOI を発行し、`README.md` と `DATA-LICENSE.md` の
      「引用」節に追記（DOI は公開の必須条件ではない）
- [ ] note 本文に図 3 枚を貼る（Markdown の表は note で崩れるため、
      表は画像化するか箇条書きへ展開する）

## 主張のチェック

以下は本リポジトリで**主張していない**ことである。書き足すときは注意する。

- 松枯れがマツタケ生産を減らしたこと（検定できなかっただけで、否定していない）
- 1983 年の補正値が正しいこと（内部整合性のみ。原典照合はしていない）
- first-stage の推定値が効果量であること（診断であって推定ではない）
- 事前トレンドが平坦であること（評価できる精度がない）
