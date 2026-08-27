# 判定量・定義・表現の監査

**STATUS: PASS**

| 項目 | v3契約 | 判定 |
|---|---|---:|
| 候補B旧複合量 | 異単位のconstraint slackとしてlegacy保存。大小・percentile・順位に不使用 | PASS |
| 候補B修正量 | 売上増、同層利益率低下、大規模利益率上昇のnullable Boolean | PASS |
| 候補C旧複合量 | `software_rotation_composite`はlegacy保存。100 percentileを最大値と解釈しない | PASS |
| 候補C修正量 | 三条件のnullable Boolean。数値percentileと候補間順位の対象外 | PASS |
| historical position | `historical_percentile_inclusive_pct`。tiesを含むinclusive empirical CDF | PASS |
| legacy rule | 旧v2判定と設定を凍結し、書き換えない | PASS |
| corrected rule | count>=3 AND rolling→persistent; count>=2 OR rolling→recent; 単期高percentile→outlier | PASS |
| 資本金区分表現 | 初出は「資本金1千万円以上1億円未満層」。以後の文脈明瞭な略記は許容 | PASS |
| 従業員給与+賞与 | 比率名は「従業員給与・賞与比率」。人件費と同一視しない | PASS |
| 人件費率 | e-Statコード093を取得した場合のみ呼称可 | PASS |
| 会計ブリッジ | 人件費は売上原価・販管費に含まれるため重複加算しない | PASS |
| claim所属 | 明示的mapping registryを使用。文字列部分一致は廃止 | PASS |

経常利益は「本業のもうけ」と表現しない。営業外収益の特定要因はこの統計だけで断定しない。

継続標本系列は通常系列よりサンプルサイズが小さく、営業利益・経常利益の標準誤差率は財務省が算出していない。
