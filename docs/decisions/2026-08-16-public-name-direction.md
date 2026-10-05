# 正式名称と識別子移行の方針

- Status: accepted
- Date: 2026-08-16
- Decision owner: Owner
- Applies to: プロジェクト全体の正式名称、名称の使い分け、実際の識別子変更へ進む前の条件
- Does not authorize: ローカルフォルダ、公開リポジトリ、組織名、ドメイン、CLI、Skillのパス、ロゴの即時変更、現在インストールされている配布パッケージの切替、商標上の安全性の断定、外部公開

## Context

2026-08-06の[公開概念体系と役割の言い方](2026-08-06-public-concept-and-role-language.md)は、Ashibaを全体概念、Keep the Ashibaを方法、Stewardを役割族、Agent等をruntime / adapterとした一方、公開project等の実改名を未決として残しました。

2026-08-16までに、名称候補の英語としての自然さ、既存利用、GitHubと主要package registryの識別子、domain、日米・国際横断の商標情報を予備調査し、外部AIの第二意見をOwner判断と分けて照合しました。完全一致の不在や取得不能は、安全、空き、登録可能を意味しません。特に`Ashiba`と`Steward`は、AI・softwareに近い既存利用と第42類の出願・登録があるため、実移行の前に限定的な再確認を要します。

同日、Ownerは、運用が独立して回り始める機会にプロジェクト全体の名称を確定し、現行文書をその名称へ切り替える方針を承認しました。外部へ公開する識別子の変更とは分け、repository内の正式名称を先に一致させます。

移行前棚卸し後、Ownerは、別ブランチを作らず正式ブランチ`master`へ対象限定のコミットとして、ソース上の配布名、プロジェクト内の自己識別子、現行の入口・設計・テンプレートを`ashiba-steward`へ先行移行することを承認しました。ローカルフォルダ、公開リポジトリ、現在インストールされている編集可能パッケージ、非公開対象一覧、Skillのパスはこの段階で変更しません。

予備調査で確認した主な外部根拠は次です。いずれも2026-08-16時点のsnapshotであり、法的なclearanceではありません。

- [Ashiba Research](https://ashibaresearch.com/)と[公開中の研究・製品](https://ashibaresearch.com/writing): AI workload、compute evidence、ML kernel、coding agentに近い現在の利用。
- [フランスINPIの`Ashiba`出願FR5265867](https://data.inpi.fr/marques/FR5265867): 第35・38・42類の出願記録。
- [J-PlatPat](https://www.j-platpat.inpit.go.jp/t0100): `ASHIBA SYSTEM`登録6121812（第9・42類）、`ASHIBA 8`登録6975407（第42類）、`STEWARD`商願2026-076792（第42類）を予備確認。
- [ファーストアカウンティングのSteward利用規約](https://www.fastaccounting.jp/useragreement-steward/): AIサービスとしての現在の利用。
- [USPTOの検索指針](https://www.uspto.gov/trademarks/search/federal-trademark-searching)と[TMview](https://www.tmdn.org/tmview/#/tmview): 完全一致だけで安全とせず、類似する名称と関連する商品・役務を別に確認するための入口。

## Decision

### 1. 正式名称

プロジェクト全体の正式名称を**Ashiba Steward**とします。

現行の規範文書、入口文書、Skill、利用者向け表現はこの名称を使います。旧称**Project Steward Agent**は、物理識別子と過去の記録を追うために必要な箇所だけへ残します。

これはローカルフォルダ、公開リポジトリ、組織名、ドメイン、CLIを同時に改名する判断ではありません。ソース上の配布名とプロジェクト内の自己識別子の先行移行は、後述の段階的な移行判断で別に扱います。

### 2. 概念体系を維持する

既存の層を統合せず、次の使い分けを維持します。

- **Ashiba**: 全体概念。
- **Keep the Ashiba（KTA）**: 方法・実践。
- **Steward**: 役割族。
- **Ashiba Steward**: 公開project・製品、およびこのプロジェクト全体を指す正式名称。
- **Agent、Skill、CLI、人間の手順**: 交換可能なruntime / adapter。

製品を指す時は`Ashiba Steward`の2語で書き、`Steward`単独は役割の意味に使います。`Agent`は正式名称へ含めず、実装や検索用の説明語として必要な場合だけ使います。オーナー付きStewardと個別プロジェクト付きStewardという配置説明、およびButler / Caddieという内部呼称は変更しません。

### 3. 識別子を段階的に移行する

現在の使い分けは次です。

- ソース上の配布名: `ashiba-steward`
- プロジェクト内の自己識別子: `ashiba-steward`
- Pythonのimportパッケージ: `pma`
- CLI: `pma`
- ローカルフォルダ・公開リポジトリ名: `project-steward-agent`のまま
- 現在インストールされている編集可能パッケージ: 作業の区切りで切り替えるまで`project-steward-agent`のまま
- Skillのパスと識別子: 運用接続部と同時に確認するまで`skills/project-steward` / `project-steward`のまま
- 非公開対象一覧のプロジェクト識別子: Butlerの許可範囲で全関連行を同時に移すまで変更しない

`Project Steward Agent`は旧称として履歴、過去の判断、既存物の説明にだけ残し、現在のプロジェクト名としては使いません。

公開リポジトリは、裸の`ashiba`ではなく`ashiba-steward`を移行先とします。ただし、取得、変更、予約は外部変更の後続判断まで行いません。ソース上の配布名を変えたことは、PyPIへの登録、公開、名前の予約を意味しません。

### 3.1 `pma`の現在の意味

CLI名は短い`pma`を維持し、現在は**Project Memory Anchor**と読みます。日本語では「プロジェクトの運用記憶の取付点」と説明します。

`pma`の歴史的な展開形は正本に記録されていません。そのため、Project Memory Anchorが当初からの正式名称だったとは扱わず、現在の機能と境界を説明するために採用した読み方として記録します。

ここでいう取付点は、新しい記憶保管庫ではありません。Git、状態文書、判断記録、対象一覧など、運用記憶がすでに残っている場所です。各commandは次のように説明します。

- `scan`: いま見るべき取付点を見つける。
- `followups`: 取付点へ戻る時期が来たプロジェクトを選ぶ。
- `handoff`: 受け渡しに添える浅い観測を作る。

`pma`はAshiba Steward全体ではなく、Stewardが使う軽量な補助センサーです。新しい記憶保管庫を作らず、既定では読み取り専用で観測と報告を行います。`scan --save-report`を明示した場合だけプロジェクト内へレポートを保存します。プロジェクト状態の修正、commit、通知、受領、意味の判断、follow-upの完了は行いません。この判断では`ashiba`または`ashiba-steward`というCLI aliasも追加しません。

### 4. 実移行の前提

repository、package、organization、domain、CLI、ロゴのいずれかを変更する前に、少なくとも次を確認します。

1. 現在何が、どこに、どの名称、remote、tag、commitで公開されているか。
2. フランスの`Ashiba`第42類出願、日本の`ASHIBA SYSTEM`・`ASHIBA 8`、日本の`STEWARD`第42類出願、およびAI・software分野の現在の利用状況を踏まえた限定的な名称確認。
3. 実際に変更する識別子ごとの取得可否と、既存利用者・履歴・リンク・CLI互換性への影響。
4. 変更対象、移行方法、旧名称からの導線、rollback、publication stateを定めた後続のaccepted decision。

調査結果には確認日を持たせ、出願中の情報や現在の利用状況を恒久的な事実として扱いません。

## 2026-08-16の移行前棚卸し

この節は、外部変更を行わない読み取り専用の棚卸し結果です。リポジトリ、パッケージ、フォルダ、公開物を変更する許可ではありません。

| 対象 | 確認した事実 | 移行上の意味 |
| --- | --- | --- |
| ローカルGit | 正式ブランチは`master`、確認時のHEADは`8d00cc0`。リモートとローカルタグはない | 公開リポジトリへpushできる接続はなく、公開済み履歴をローカル履歴の祖先と推測しない |
| 公開GitHub | `Bourbon-OS/project-steward-agent`は文書だけのv0.2として存在する。既定ブランチ`main`のHEADは`9b34688`、公開準備ブランチ`codex/v0.2-public-docs`は`461e958`、`v0.2`は注釈付きタグ`17a275`から`9b34688`を指す | 現在のローカル実装と公開物はブランチ名も履歴も別であり、改名とコード公開を同じ操作にしない |
| Git履歴の接続 | 公開コミット`9b34688`とその親はローカルのオブジェクトデータベースに存在せず、ローカルのルートコミットは`80cc0f3` | force pushや履歴の置換を使わず、公開履歴を残す接続方法が必要 |
| GitHub候補名 | `Bourbon-OS/ashiba-steward`は公開リポジトリとして到達できなかった | 空きまたは取得権限を証明しないため、実行直前に認証済みのGitHub設定画面で確認する |
| ローカルの配布パッケージ | 編集可能な`project-steward-agent 0.1.0`が現行フォルダを参照し、コマンドは`pma`だけが存在する | 配布名とフォルダを変えた後に旧メタデータを除去し、再インストールする。CLIは変えない |
| PyPI | `project-steward-agent`と`ashiba-steward`は、確認時点の公開索引で一致する配布パッケージなし | 最初の公開前なら配布名を選び直せるが、予約済みまたは将来も利用可能とは断定しない |
| 追跡中の参照 | 現行の物理名は主に`.project-agent.yml`、`pyproject.toml`、READMEのhandoff例と移行中の説明に残る。追跡中のファイルに旧公開URLやローカル絶対パスはない | 現行識別子だけを変更し、過去判断・調査・過去のプロジェクト作業名は履歴として残す |
| 実行接続部 | ローカルの自動実行定義から旧名称または正式名称の直接参照は見つからなかった | Butlerや非公開対象一覧の参照がない証明ではない。運用側は別の許可範囲で確認する |
| 公開ライセンス | 公開v0.2は文書をCC BY 4.0としている一方、ローカルの追跡中ファイルには`LICENSE` / `NOTICE`がない | 現行コードを公開リポジトリへ載せる前に、コードと文書のライセンス境界をOwnerが決める |

## 推奨する移行順

### 1. ローカル識別子を正式ブランチへ直接反映する

別ブランチは作らず、外部変更前に正式ブランチ`master`への対象限定コミットとして次だけを変更します。

- 配布名とプロジェクト内の機械識別子を`ashiba-steward`へ変える。
- READMEの現行例、入口、設計、テンプレートを新しい物理名へ合わせる。
- `src/pma`、Pythonのimport名、コマンド`pma`は維持する。
- 過去判断、調査、過去の作業名、旧公開物を機械的に書き換えない。
- 全自動試験、パッケージのメタデータ、`pma`の三つのコマンドを確認する。

この対象限定コミットでは、フォルダ、現在インストールされている配布パッケージ、GitHub、非公開対象一覧、Skillのパスを変更しません。全試験と差分を確認してからコミットし、途中状態を正式ブランチ外へ残しません。

### 2. ローカルフォルダと編集可能パッケージは作業の区切りで切り替える

現在のCodex作業と編集可能パッケージは旧パスを参照しているため、作業途中ではフォルダを移動しません。移行コミットと再開手順を確認した区切りで、旧パッケージの削除、フォルダの`ashiba-steward`への移動、新しいパスからの再インストール、`pma --help`と三つのコマンドの再確認を一続きで行います。途中で失敗した場合はフォルダを旧名へ戻し、旧パッケージを再インストールできる状態を先に確認します。

### 3. オーナー側の識別子は全履歴行を一つの変更として扱う

非公開対象一覧の`プロジェクト`列は、対象行とevent受領記録の両方で候補の表示・集約に使われます。片側だけを改名すると同じプロジェクトが二つに分かれて見えるため、Butlerの許可範囲で該当する対象行と全event行を一つの対象限定編集として変更し、同じ基準日の`pma followups`を変更前後に実行して候補の意味が変わらないことを確認します。新しい別名台帳は作りません。固定作業やローカルパスはプロジェクト識別子とは別の確認先として更新します。

### 4. 公開repositoryは履歴を置き換えず一つへ接続する

公開v0.2とlocal実装は別履歴なので、force pushで公開`main`を置き換えません。実装を公開できる条件がそろった時点で、公開`main`と`v0.2`を取得し、公開`main`をancestorに含む明示的な接続commitをrelease候補上で作り、tree、tag、旧文書への導線を独立cloneで確認します。公開default branchとlocal canonical branchはその時点で`main`へ揃え、closure gateと現行導線も同じ移行commitで更新します。

その後に既存GitHub repositoryを`ashiba-steward`へ改名し、接続済み履歴だけをfast-forwardで反映します。GitHubは通常のweb / Git操作を旧URLからredirectしますが、GitHub Pagesのproject URLとrenamed repository上のAction呼び出しは同じ扱いではありません。旧slugを再利用するとredirectが壊れるため、旧名は再利用しません。実行直前にActions、Pages、権限、候補名を認証済み設定で再確認します。

### 5. コード公開とpackage公開は改名から分ける

現行実装を公開する前に、コードのlicense、公開対象、機密・個人情報、生成物、実運用データ、release manifestを確認します。PyPIへの最初のupload、GitHub release、tag追加は、repository改名やlocal package名変更の成功から推測せず、別の公開判断として扱います。

## Rollback

- ローカル変更は対象限定コミットへ閉じ、問題が見つかった場合は履歴を消すresetではなく、確認済みの後続修正で戻す。
- フォルダ移動と編集可能パッケージの切替は、旧パスと旧配布パッケージを復元できる順序を確認してから行う。
- GitHub改名前にowner、旧slug、default branch、HEAD、tagを再記録する。改名を戻す場合も旧slugが再利用されていないことを確認する。
- 公開履歴をforce pushまたは削除で戻さない。公開後の訂正は後続commitとrelease状態で行う。
- PyPIへuploadする前は公開distributionがない状態を維持し、upload後の削除を通常のrollback手段にしない。

## Consequences

- `Ashiba Steward`を現行文書の正式名称として使いますが、物理識別子の移行完了、外部公開、商標上の安全を意味しません。
- 過去資料は当時の記録として機械的に書き換えず、必要に応じてこの判断への導線を加えます。
- `Ashiba`または`Steward`単独へブランド上の意味を集約しません。
- `Agent`を名称から外すことで、人間、Skill、CLI、Codex以外のAI環境を含むruntime交換可能性と名称を一致させます。
- ソース上の配布名とプロジェクト内の自己識別子は`ashiba-steward`へ先行移行します。フォルダ、公開リポジトリ、現在インストールされている配布パッケージ、Skillのパスは各境界の確認まで変更しません。
- CLI名は`pma`を維持し、Project Memory Anchorという現在の読み方と、補助センサーとしての境界を一緒に示します。
- この判断は[確定判断のclosure gate](2026-08-02-decision-closure-gate.md)に従い、正式ブランチ`master`上の対象限定コミットへ反映し、公開状態を`local commit only`として確認します。

## Alternatives not adopted

| Alternative | Reason |
|---|---|
| `Ashiba Agent` | Agentは交換可能なruntimeの一つであり、Stewardの責任、非所有、継続性を名称から失う |
| `Ashiba Steward Agent` | 概念、役割、runtimeを一つの名称へ積み、現行名と同型の構文衝突を残す |
| `Project's Ashiba ...` | 固有名として不自然で、公開identifierにも適さない |
| `Project of Ashiba ...` | 英語の名称として不自然で、対象projectと製品名の曖昧性も残る |
| 裸の`Ashiba`を公開identifierにする | 既存のsoftware利用があり、全体概念と実装projectを再び同じ層へ重ねる |
| CLIを`ashiba`または`ashiba-steward`へ変える | 現行機能はAshiba Steward全体ではなく補助センサーであり、短い既存commandを移行する負担に見合う機能上の利点がない |
| 直ちに全識別子を改名する | 公開実態、名称利用可否、移行範囲が未確認 |

## Related sources

- [公開概念体系と役割の言い方](2026-08-06-public-concept-and-role-language.md)
- [Stewardの役割族・配置・内部呼称](2026-08-02-steward-role-placement.md)
- [確定判断のclosure gate](2026-08-02-decision-closure-gate.md)
- 命名クリアランス調査（開発資料：`../research/naming_clearance_2026-07-31.md`、本配布では省略）
- [GitHub: Renaming a repository](https://docs.github.com/en/repositories/creating-and-managing-repositories/renaming-a-repository)
- [Python Packaging User Guide: Distribution package vs. import package](https://packaging.python.org/en/latest/discussions/distribution-package-vs-import-package/)
- [Python Packaging User Guide: Writing your pyproject.toml](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/)
