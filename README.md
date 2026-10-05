# Ashiba Steward v0.3

**未来の自分や次の担当者が、理由を辿って仕事へ戻れるように。**

成果物が残っていても、「なぜこうしたか」「何が仮対応か」「何が未完了か」がチャットや担当者の記憶に散ると、再開するたびに背景を復元することになります。Ashiba Stewardは、既にあるGit、文書、判断記録を足がかりに、目的と理由と戻り先を薄く保つ考え方、運用手順、軽量な補助CLIです。

この候補は公開前のローカル配布候補です。コード等はMIT、文書・Skill等はCC BY 4.0の方針を反映しています。[適用範囲と全文](LICENSE.md)、[候補状態](PROJECT_STATUS.md)を確認できます。

## この公開で伝えたいこと

仕事を記録のために止めず、後から戻るための足場を保ちます。たとえば、仮対応には仮である理由と見直す条件を、休止した仕事には休止理由と戻る条件を、引き継ぐ判断には結論だけでなくその理由への導線を残します。活動量や文書の量を増やすことを目的にしません。

Ashibaは再開と引き継ぎの足場、Keep the Ashiba（KTA）はそれを維持する実践、Stewardはその実践を支える役割です。オーナーに付くStewardをButler、一つのプロジェクトに付くStewardをCaddieと呼びます。手順・Skillでも、この配置を示す呼称を使います。

旧称はProject Steward Agent（PSA）です。方法、役割、実行する道具を分け、AIエージェントだけでなく人間が行う実践も表すため、製品名をAshiba Stewardへ整理しました。旧版の目的と記録を引き継ぐ改名で、別の製品をゼロから始めたという意味ではありません。CLIとPythonのimport名は`pma`を維持します。

公開v0.2ではこの考え方を文書で共有しました。v0.3では、読んだ考え方を自分の環境で試せるように、手順、ひな形、観測CLIを添えます。[コンセプト](docs/concept.md)、[KTA原則](docs/principles.md)、[今回添えたもの](RELEASE_NOTES.md)へ進めます。

考え方を読む場合は[文書の入口](docs/index.md)、試す場合は[最小の導入](docs/getting-started.md)から始めてください。

## 何が入っているか

| 内容 | 用途 |
| --- | --- |
| [共通運用Skill](skills/project-steward/SKILL.md) | オーナー付きSteward（内部呼称Butler）と個別プロジェクト付きSteward（Caddie）の導入、連携、許可後の修復、完了確認 |
| [Caddieの背景確認](skills/check-caddie-context/SKILL.md) | 情報の所在、変更の理由、判断の背景を確認する |
| [Butlerの結果受領](skills/receive-butler-result/SKILL.md) | 既存の依頼への回答を受け取り、許可された浅い一覧更新を行う |
| [Butlerの通常・定期確認](skills/review-butler-projects/SKILL.md) | 対象一覧全体の未完了、期限、未回収結果を見て次の対応を選ぶ |
| `pma scan / followups / handoff` | 浅い観測、確認候補、引き渡し用の観測を作る |

用途別入口は必要な手順だけを読みます。これらのSkillはAIまたは人間が実行する手順であり、常駐アプリ、AIサービス、スケジューラーではありません。

Work Map、Work Thread、GUI、外部レビュー追跡の試行機能、製品開発専用Skill、個人別の実運用一覧は含みません。Work Mapは目的・現在地・理由を保つ別の足場として、[別配布の位置づけと導入条件](docs/getting-started.md#6-work-mapの別配布)を案内しています。Stewardへの統合や統合版の時期は未決です。

旧v0.2のMVP目標は、検知・受領、背景回収、許可後の修復、結果確認、必要なフォローまでの一巡でした。この目標は[要件](docs/requirements.md)と[設計](docs/design.md)へ引き継いでいます。CLIの観測成功だけでは全体の達成になりません。管理された確認と、通常運用で偶発的に失われた文脈を救う効果を分け、後者は未確認です。[旧MVP計画の版固定原文](https://github.com/Bourbon-OS/project-steward-agent/blob/9b34688ae291cd504295c5b7cadc3ac788cde382/docs/mvp_plan.md)も辿れます。

## 始める

1. [導入ガイド](docs/getting-started.md)から、Butler/Caddieの配置と読み取り範囲を決めます。
2. 同じ配布一式のSkillと参照資料を読めるようにします。名前やハッシュだけでは接続済みになりません。
3. 必要な場合だけ、次の方法でCLIを使います。

Python 3.11以上とGit CLIがあれば、展開先でインストールなしでも動作確認できます。架空サンプルは、配布元のGitフォルダの外へコピーしてから初期化します。以下は新しい試用フォルダを作る例です。初回scanでは初期commitがないため`at_risk`等の指摘が出る想定で、失敗や実案件の判断を意味しません。既存の実プロジェクトには初期化を行わず、許可されたpathを指定します。

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
python -X utf8 -m pma --help
$trialPath = Join-Path ([System.IO.Path]::GetTempPath()) ('ashiba-example-' + [guid]::NewGuid().ToString('N'))
Copy-Item -LiteralPath ./examples/sample-project -Destination $trialPath -Recurse
git -C $trialPath init
python -X utf8 -m pma scan --path $trialPath
python -X utf8 -m pma followups --list ./examples/project_list.md --as-of 2026-09-30
python -X utf8 -m pma handoff --path $trialPath --project example-project --trigger manual
```

配布候補をローカルへ導入して確認する場合：

```powershell
python -m pip install .
pma --help
```

このCLIの配布名は`ashiba-steward`、Python package versionは`0.1.0`です。製品候補の`v0.3`とは別の版です。今回の候補では、読み取り時のGitの任意更新を抑止する限定補修を加え、既存の部品版を維持しています。名前や版から未確認の機能を推測しないでください。

## 安全と制限

- `pma`は既定で読み取り専用です。修復、commit、通知、AIの起動は行いません。
- 設定がない時は観測範囲に差があります。`scan`は状態文書を正本と推測せず未確認とし、`handoff`は既定位置の`PROJECT_STATUS.md`を読みます。`ready`や読み取れた状態値は、正本・背景・未完了を全面確認した証拠ではありません。[導入時の観測前提](docs/getting-started.md#5-cliを補助として使う)を確認してください。
- `scan --save-report`を明示した時だけ、設定されたプロジェクト内の保存先へレポートを書きます。
- `followups`の候補0件は「全体として仕事なし」ではありません。宣言された一覧を機械的に選別する補助で、意味判断や未完了の照合はSteward側が担います。
- `next_review`の日付を書くだけでは自動実行されません。実際に起動する人、AI環境の定期実行、または既存スケジューラーと、結果の受け取り先が必要です。
- 読み取り量は、宣言された毎回読む情報の合計を観測します。条件付き資料は混ぜず、文字数からtoken数やCodexのクレジット消費を固定比率で推定しません。token測定は任意です。
- 相手から「承認済み」と聞いただけでは変更許可を増やしません。秘密情報、公開、削除等には実際の許可境界を適用します。

詳しい原則は[KTA原則](docs/principles.md)、仕様は[要件](docs/requirements.md)と[設計](docs/design.md)を参照してください。これらは基準commitの文書で、まだ未実装の要件も含みます。実装範囲は[この候補の状態](PROJECT_STATUS.md)と照合してください。

## 再確認

Windowsの既存試験は、UTF-8と候補内の一時フォルダを設定する入口を使います。

```powershell
pwsh -NoProfile -File tools/run-tests.ps1
```

試験はローカル機能と参照契約の確認であり、別環境や別モデルでの通常運用効果を保証しません。[内容と出典](MANIFEST.json)に、基準commit、各ファイルのハッシュ、配布用の導線変更を記録しています。

ライセンスの適用範囲・全文は[LICENSE](LICENSE.md)、著作者表示と変更の説明は[NOTICE](NOTICE.md)を参照してください。
