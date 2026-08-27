# Phase 0 アーカイブと旧出力の監査

**STATUS: PASS**

## 完全性の実査

| 必須要素 | リポジトリ | 旧ZIP |
|---|---:|---:|
| `config` | PASS | FAIL |
| `data/raw` | PASS | FAIL |
| `outputs/2026Q1` | PASS | FAIL |
| `outputs/2026Q1_v2` | PASS | FAIL |
| `src` | PASS | FAIL |
| `tests` | PASS | FAIL |
| `README.md` | PASS | FAIL |
| `pyproject.toml` | PASS | FAIL |
| `requirements.lock` | PASS | FAIL |

欠損はinventoryから判定した。Phase 0開始時の旧ZIP実査では必須要素がすべて存在した。その後旧ZIPはワークスペース上で参照不能となったため、最終完全性判定は現リポジトリの全件inventoryによった。推測で欠損扱いしていない。

## 凍結出力のSHA-256

- v1: 14ファイル / inventory digest `815bc636ad3725c80389b40b63dc567a1969e2382ec57544c9b73214a8b10914`
- v2: 24ファイル / inventory digest `5d70d458583f42ea487968bbbd22f233ee41c6b85a1123d790fbf3ce7222568c`
- 合計: 38ファイル / `885516ec9fb90a5b7dda680d08b8393f2ebf66cf455fe99e7d0bb6863fc5ca8b`
- 個別ファイルのパス・バイト数・SHA-256は `clean_archive_manifest.json` に全件保存。

## 旧ZIPとclean package

- 旧ZIP: `アーカイブ.zip` / 294 members / SHA-256 `None`
- 公開不要member: 186件
- 除外: `__MACOSX`, `__pycache__`, `.DS_Store`, `.pytest_cache`。旧ZIPと出力ZIP自身もネストしない。
- 再現可能コマンド: `make package-v3`

## テストと失敗分類

- 変更前の収集件数: 95件
- v3追加後の収集件数: 166件
- 依存関係チェック: PASS
- `ModuleNotFoundError` / `ImportError` / doctor不合格は `DEPENDENCY_FAILURE`。 統計契約、raw/manifest、ハッシュ、加算、記事ゲートの不合格は `CODE_OR_DATA_FAILURE`。

継続標本系列は通常系列よりサンプルサイズが小さく、営業利益・経常利益の標準誤差率は財務省が算出していない。
