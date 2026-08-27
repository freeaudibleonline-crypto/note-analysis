# 食い違いは小規模資本金層に集中していた――法人企業統計、二つの推計を41四半期並べる <!-- central-claim: V31-SMALL-MARGIN-DIRECTION-MISMATCH --> <!-- claim: V31-SMALL-MARGIN-DIRECTION-MISMATCH -->

## 要旨

財務省の法人企業統計には、各期の通常系列と、回答を継続した企業を用いる継続標本系列がある。本稿では資本金1千万円以上1億円未満層を扱い、以下「小規模資本金層」と記す。両系列を2016年1～3月期から2026年1～3月期まで並べると<!-- claim: V31-SMALL-MARGIN-DIRECTION-MISMATCH -->、小規模資本金層の営業利益率の上昇・低下方向は16/41四半期、39.0％<!-- claim: V31-SMALL-MARGIN-DIRECTION-MISMATCH -->で食い違った。この記事の主張は、この不一致が資本金階層間で均等ではなく、小規模資本金層に集中して観察された、という一点である。

ただし、これは将来の頻度を示す評価ではない。16/41<!-- claim: V31-SMALL-MARGIN-DIRECTION-MISMATCH -->と11/41<!-- claim: V31-COMPOSITE-HEADLINE-MISMATCH -->はいずれも、2026Q1の結果を見た後に過去へ適用した探索的バックテストである。後者は複数条件を組み合わせた見出しの成立可否であり、本文の主数値ではなく補足に置く。

## 何を比べたのか

通常系列と継続標本系列は、単に同じ真値を異なる標本で測った二つの推計とは限らない。企業の参入・退出、回答継続条件、推計用乗率、未回答補完、母集団構成の違いを含み得る。どちらの系列も真実や正解とは呼ばない。片方を基準にもう片方の優劣を決める比較ではなく、見出しの感応度を系列の構成差とともに記述する作業である。

継続標本では営業利益率水準が公表されていない。そこで、売上高前年比と営業利益前年比から推定した利益率の相対変化率（％）の符号だけを使い、上昇・低下の方向判定だけに限定した。「何ポイント変化した」という比較は行っていない。通常系列にも同じ変換を適用し、同じ定義で並べた。

![資本金階層と指標別の不一致率](charts/mismatch_heatmap.png)

図1の最上段が主結果である。利益率方向の不一致は小規模資本金層で16/41（39.0％）<!-- claim: V31-SMALL-MARGIN-DIRECTION-MISMATCH -->、中堅資本金層で6/41（14.6％）<!-- claim: V31-MISMATCH-MIDDLE-MARGIN-DIRECTION -->、大規模資本金層で0/41（0.0％）<!-- claim: V31-MISMATCH-LARGE-MARGIN-DIRECTION -->だった。

利益率方向だけの現象でもない。営業利益前年比の符号は小規模31.7％<!-- claim: V31-MISMATCH-SMALL-OPERATING-PROFIT -->、中堅9.8％<!-- claim: V31-MISMATCH-MIDDLE-OPERATING-PROFIT -->、大規模0.0％<!-- claim: V31-MISMATCH-LARGE-OPERATING-PROFIT -->で不一致だった。売上高前年比の符号は小規模15.0％<!-- claim: V31-MISMATCH-SMALL-SALES -->、中堅17.1％<!-- claim: V31-MISMATCH-MIDDLE-SALES -->、大規模2.4％<!-- claim: V31-MISMATCH-LARGE-SALES -->である。指標によって細部は違うが、営業利益と利益率方向では小さい資本金階層ほど食い違いが多い。

## 変化幅だけでは説明できない

大規模資本金層の一致を「変化幅が大きいから」と説明できるかも確認した。継続標本について、判定余裕を営業利益増加率と売上高増加率の差の絶対値と定義すると、中央値は小規模11.3％<!-- claim: V31-SMALL-DECISION-MARGIN-MEDIAN -->、中堅9.0％<!-- claim: V31-MIDDLE-DECISION-MARGIN-MEDIAN -->、大規模8.5％<!-- claim: V31-LARGE-DECISION-MARGIN-MEDIAN -->だった。大規模の判定余裕が最大だったわけではない。

両系列の「営業利益前年比－売上高前年比」の差を取り、その絶対値の中央値を見ると、小規模11.21ポイント<!-- claim: V31-SMALL-SERIES-DIVERGENCE-MEDIAN -->、中堅4.07ポイント<!-- claim: V31-MIDDLE-SERIES-DIVERGENCE-MEDIAN -->、大規模1.05ポイント<!-- claim: V31-LARGE-SERIES-DIVERGENCE-MEDIAN -->だった。系列間の乖離そのものが小規模側で大きい。この結果からは「大企業は変化幅が大きいから一致する」という説明は支持されないが、別の仕組みを原因として特定するものでもない。

通常系列では、非金融法人について資本金5億円未満を標本抽出し半数をローテーションする一方、5億円以上は全数選定でローテーションしない<!-- claim: V31-CENSUS-THRESHOLD -->。資本金1億円以上10億円未満層はこの境界をまたぐ。資本金階層別の不一致勾配は調査設計と整合的である。ただし、全数か標本かだけで結果が決まるとはいえない。継続回答条件や乗率、補完、母集団構成も同時に異なり得るからだ。

## 複合見出しの2×2表

![複合見出しの2×2表](charts/headline_2x2.png)

「大規模資本金層は利益率が改善し、小規模資本金層は悪化する」という複合見出しは、通常系列だけで9回<!-- claim: V31-HEADLINE-2X2-REGULAR-ONLY -->、継続標本系列だけで2回<!-- claim: V31-HEADLINE-2X2-CONTINUING-ONLY -->、両方で1回<!-- claim: V31-HEADLINE-2X2-BOTH -->成立し、どちらでも成立しなかったのが29回<!-- claim: V31-HEADLINE-2X2-NEITHER -->だった。成立回数を系列別に足すと通常系列10回<!-- claim: V31-HEADLINE-REGULAR-TOTAL -->、継続標本系列3回<!-- claim: V31-HEADLINE-CONTINUING-TOTAL -->となる。これは2×2表にみられる非対称の記述であり、通常系列の調査上の失敗を意味しない。

系列間でこの見出しの成立可否が違ったのは11/41四半期<!-- claim: V31-COMPOSITE-HEADLINE-MISMATCH -->である。ただし、これは三つの条件を束ねた補足指標だ。異なる尺度を一つの複合数値へ混ぜず、条件を満たしたか否かだけを数えた。主結果はあくまで利益率方向そのものの16/41<!-- claim: V31-SMALL-MARGIN-DIRECTION-MISMATCH -->である。

## 二つの頑健性確認

第一は公表値の丸めに対する感応度である。継続標本の売上高前年比と営業利益前年比の各公表値に±0.05ポイント<!-- claim: V31-ROUNDING-HALF-WIDTH -->の区間を置き、両者の差の絶対値が0.1ポイント<!-- claim: V31-ROUNDING-AMBIGUITY-THRESHOLD -->以下なら NOT_DETERMINED_BY_ROUNDING とした。該当は0件<!-- claim: V31-ROUNDING-AMBIGUOUS-COUNT -->で、最小の判定余裕は2018Q2の0.5ポイント<!-- claim: V31-ROUNDING-MINIMUM-MARGIN -->だった。これは表示丸めに限った確認であり、標本誤差は別途未定量である。

第二はデッドバンドである。両系列の推定変化がともに±dの外側にある四半期だけを残した。単位は営業利益率の絶対ポイント差ではなく、売上高前年比と営業利益前年比から推定した利益率の相対変化率（％）である。

![デッドバンド感応度](charts/deadband_sensitivity.png)

小規模資本金層は、±0.5％で15/39<!-- claim: V31-DEADBAND-SMALL-D005 -->、±1％で14/37<!-- claim: V31-DEADBAND-SMALL-D010 -->、±2％で10/33<!-- claim: V31-DEADBAND-SMALL-D020 -->、±3％で8/29<!-- claim: V31-DEADBAND-SMALL-D030 -->となった。±3％では不一致率が小規模27.6％<!-- claim: V31-DEADBAND-SMALL-D030 -->、中堅0.0％<!-- claim: V31-DEADBAND-MIDDLE-D030 -->、大規模0.0％<!-- claim: V31-DEADBAND-LARGE-D030 -->で、小規模側の食い違いが残る。閾値を動かしても階層差が消える形ではなかったが、閾値は分析者が置いた感応度設定である。

さらに、継続標本の営業利益増加率の絶対値が100％<!-- claim: V31-EXTREME-YOY-THRESHOLD -->を超えた3件<!-- claim: V31-EXTREME-YOY-FLAGGED -->へ、NEAR_ZERO_BASE欄の機械的レビュー印 EXTREME_YOY_RATE_GT_100 を付けたが、名称にかかわらず低ベースやゼロ近傍を示す証拠とは扱わない。その全てが方向不一致ではなかった<!-- claim: V31-EXTREME-YOY-MISMATCH -->。歴史窓の分母を41四半期<!-- claim: V31-SMALL-MARGIN-DIRECTION-MISMATCH -->に固定した帰属確認では、利益率方向16/41<!-- claim: V31-SMALL-MARGIN-DIRECTION-MISMATCH -->と複合見出し11/41<!-- claim: V31-COMPOSITE-HEADLINE-MISMATCH -->の件数は変わらない。これは分母を減らす完全ケース再推計ではない。

## 読み方の限界

継続標本は通常系列より標本数が小さく、営業利益・経常利益の標準誤差率が算出されていない。このため、ここで示した差について標本誤差を数値化して比較することはできない。丸め感応度で判定不能がなかったことと、未定量の標本誤差とは別問題である。

また、継続標本は固定された企業集合を無条件に追跡する資料ではない。回答の継続、企業の状態変化、集計対象の条件を踏まえる必要がある。通常系列はその時点の母集団を表すための推計であり、継続標本系列は継続回答企業の動きを確認する補助資料である。それぞれの目的が違う以上、系列間の食い違いを一方の欠陥へ置き換えない。

以上から公開記事で採用する主張は一つに限る。法人企業統計の利益率方向の食い違いは、観察した41四半期では小規模資本金層に集中していた。これは調査方式による因果を確定する結論ではなく、二つの系列を併記したときに見出しがどこで揺れやすいかを示す記述的な監査結果である。<!-- claim: V31-SMALL-MARGIN-DIRECTION-MISMATCH -->
