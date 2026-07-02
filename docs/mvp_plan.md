# MVP計画

公開版メタデータ:

- バージョン: 0.1
- 作成日: 2026-07-03
- ライセンス: Creative Commons Attribution 4.0 International (CC BY 4.0)
- 著作者表示: Bourbon-OS
- 推奨表示: Bourbon-OS, Project Steward Agent 公開ドキュメント v0.1 (2026-07-03), CC BY 4.0

## 位置づけ

この文書は、これまでの調査とスコープ整理を受けて、Project Steward Agent の初期 MVP を実装に入れる直前の最小判断としてまとめたものです。

調査フェーズはいったん閉じます。MVP は、1 つのローカル Git プロジェクトを対象にした軽量な足場レビューに絞ります。ユーザーに返すものは、管理フレームワークではなく、短い Markdown レポートと「ご確認いただきたいこと 1 件」です。

## MVPでやること

MVP は読み取り中心です。ファイルの自動修正、自動 close、自動 archive、自動通知はしません。

- ローカル Git リポジトリを対象にする。
- 最初の CLI 名は `pma` とし、最初のコマンドは `pma scan` とする。
- `git status --short` で未コミット変更と未追跡ファイルを確認する。
- 直近のコミット日時を確認する。
- `README.md`、`PROJECT_STATUS.md`、`.project-agent.yml` の存在を確認する。
- `.project-agent.yml` が存在する場合は、MVP の最小項目だけを読む。
- `PROJECT_STATUS.md` の `status`、`Last updated` または `last_reviewed`、推奨項目の `next_review` を確認する。
- `active` のまま長期間動いていない場合に、状態確認の候補として出す。
- `TODO`、`FIXME`、`あとで`、`未定`、`仮`、`要確認` などの足場キーワードを検知する。
- README から `docs/` 配下への導線があるかを、安い文字列チェックで確認する。
- README からプロジェクト管理方法、状態宣言、判断ログ、Steward運用への導線があるかを確認する。
- Markdown 形式の足場レビューレポートを標準出力に生成する。
- 必要に応じて、`reports/footwork_review_YYYY-MM-DD.md` にレポートを保存できる想定にする。
- `pma scan` を manual / event-driven / timing-driven の共通入口として扱う。
- event-driven は、作業後に人間または Codex が `pma scan` を呼ぶ運用までに留める。
- timing-driven は、週次や `next_review` 前後に `pma scan` を呼ぶ運用設計までに留める。
- 週次レビューや一覧レポートでは、優先対応を最大 3 件に絞る。
- 通常対話へ持ち出す確認は、原則 1 件に絞る。
- 通常対話の Stewardからのご提案は、具体案を出して「してよろしいですか？」と許可を取る形を基本にする。

MVP のレポートには、少なくとも次を含めます。

- 全体判断。
- 根拠の要約。
- findings。
- 優先対応、最大 3 件。
- 通常対話に持ち出すならご確認いただきたいこと 1 件。
- 具体案 + 許可取りの Stewardからのご提案。

## MVPではやらないこと

- GitHub Actions 前提の運用。
- システム変更計画書、承認ワークフロー、作業結果報告の代替。
- インシデント管理、障害報告、ポストモーテムの代替。
- GitHub Issue や PR への自動通知。
- Portfolio Steward Agent。
- 複雑なプロジェクト横断管理。
- LLM review。
- 自動修正。
- 依存更新 bot。
- Renovate 相当の更新エンジン。
- OpenSSF Scorecard 相当のセキュリティスコアリング。
- Backstage 相当のポータル。
- 厳密な ADR 管理システム。
- `DECISIONS.md` の必須化。
- 常駐 daemon。
- ファイル監視。
- 自動 Git hook 挿入。
- OS スケジューラ自動登録。
- 通知 bot 化。
- 会議監視、録音、文字起こし、議事録自動生成。
- 議事録ツールの再実装。
- 自動 close / archive。
- 執事キャラクター化。
- 個人秘書化や生活管理代行。

## MVPの実行モデル

MVP では、`pma scan` を 3 種類の起動タイミングで使います。いずれも同じ Cheap scan と Markdown レポートを使い、常駐や自動監視は作りません。

### manual

人間または Codex が必要な時に明示的に実行します。

```powershell
pma scan --path .
pma scan --path C:\path\to\project
```

### event-driven

作業イベントの後に実行します。MVP では完全自動イベント監視ではなく、Codex や人間が作業後に `pma scan` を呼ぶ運用にします。

想定イベント:

- Codex がファイルを変更した後。
- 設計、実装、構築作業で方針変更や暫定対応が生まれた後。
- 調査、検証、デバッグ、試行錯誤で複数の道を試した後。
- 小さな修正、慣れた作業、チャットや口頭合意など、軽く扱われやすい変更の後。
- 障害対応やトラブル対応で緊急設定変更、暫定回避、切り戻しが発生した後。ただし障害対応そのものは邪魔せず、落ち着いた後に足場を確認する。
- 引き継ぎ、担当変更、別チームへの依頼など、人に渡る作業の後。
- レビューを受けた後。
- 重要会議の後。ただし MVP では既存の会議メモや議事録がある場合の足場確認に留め、会議監視や自動議事録化はしない。
- 未追跡ファイルが増えた時。
- コミット前またはコミット後。
- `PROJECT_STATUS.md` を更新した後。
- 設定変更や本番作業の変更計画書、作業結果報告が作られた後。ただし既存の変更管理文書を置き換えず、プロジェクト側の足場から辿れるかだけを見る。
- 新しい運用ファイルや docs を追加した後。

### timing-driven

日次・週次・`next_review` 前後など、決まったタイミングで実行します。MVP では常駐 daemon は作らず、手動実行または将来の OS スケジューラ / GitHub Actions 候補として扱います。

例:

- 週1回 `pma scan --path <project> --save-report` を実行する。
- `next_review` の前後で `PROJECT_STATUS.md` を確認する。
- `active` のまま止まっているプロジェクトに、継続・休止・保留の確認を出す。

event-driven は「足場が崩れやすい瞬間に支える」ため、timing-driven は「忘れられた足場を拾う」ために使います。足場が崩れやすい瞬間には、危ないとき、急ぐとき、迷っているとき、軽く見ているとき、慣れているとき、流れで決まるとき、人に渡るときが含まれます。担当確認中・結果待ち・次回確認は timing-driven 実行で拾いやすいですが、MVP では未完了管理の自動追跡はまだ行いません。まずは `PROJECT_STATUS.md` や adoption メモに残したものを、人間または Codex が確認する運用にします。

MVP での救い方は、完全な復元ではなく、軽い回収に留めます。

- 作業中に記録を強制しない。
- 作業後に `git status`、未追跡ファイル、更新された Markdown、足場キーワードを見て、足場リスクを拾う。
- 仮、あとで、TODO、要確認、反映待ちに見えるものを、正式化・撤去・保留・次回確認の候補として出す。
- ユーザーへは、今確認すべき 1 件だけを具体案として出す。
- 既存の会議メモ、変更計画書、障害報告がある場合は、それを置き換えず、プロジェクト側の足場から辿れるかだけを見る。

## MVPで仮決めすること

- CLI 名は `pma` とする。
- 最初のコマンドは `pma scan` とする。
- レポートは標準出力に表示し、必要に応じて `reports/footwork_review_YYYY-MM-DD.md` に保存できる形にする。
- `.project-agent.yml` は存在確認の対象にする。ただし、欠落しても致命的エラーにせず、設定未整備の finding として扱う。
- `.project-agent.yml` は MVP では最小スキーマにする。
- `.project-agent.yml` が存在する場合の最小項目は、`project.name`、`project.status_file`、`project.source_of_truth`、`checks.required_files`、`stale.active_days`、`stale.paused_days`、`stale.archived_days`、`report.max_priority_actions`、`report.output_dir` とする。
- stale 判定は `.project-agent.yml` で設定可能にする。
- stale 判定の未設定時初期値は、`active` 14日、`paused` 30日、`archived` 180日とする。
- `PROJECT_STATUS.md` では `status` を必須扱いにする。
- `last_reviewed` / `next_review` は MVP では推奨項目とし、存在しない場合は警告に留める。
- `last_reviewed` がない場合は、MVP では `Last updated` で代用できるものとして扱う。
- README 未掲載ファイルの検知は、MVP では `docs/` 配下のファイル名またはパスが README に現れるかを見る安いチェックに留める。
- `DECISIONS.md` は MVP 必須にしない。未記録判断の候補がある場合に、将来の記録先または推奨ファイルとして提案する。
- 「新人期間」は設定ファイルに持たず、応答方針・設計思想に留める。

## 実装前の最小構成案

次の実装作業では、この構成を土台に MVP 最小実装を開始します。

```text
pyproject.toml
src/
  pma/
    __init__.py
    cli.py
    scan.py
    report.py
    config.py
    status.py
    git_utils.py
tests/
```

- `cli.py`: `pma scan` の入口。
- `scan.py`: ファイル存在、キーワード、Git 状態などの読み取り。
- `report.py`: Markdown レポートと Stewardからのご提案の整形。
- `config.py`: `.project-agent.yml` の読み取り、既定値、最小 validation。
- `status.py`: `PROJECT_STATUS.md` の読み取りと stale 判定。
- `git_utils.py`: `git status --short`、最終コミット日時などの Git 呼び出し。

MVP の実行例:

```powershell
python -m pma scan --path .
pma scan --path .
pma scan --path . --save-report
```

`--save-report` を指定した場合だけ、必要に応じて `reports/` を作成し、`reports/footwork_review_YYYY-MM-DD.md` に保存します。通常は標準出力だけに Markdown レポートを出します。

実装言語は Python を推奨します。理由は、Git の subprocess 呼び出し、ファイル走査、日付処理、Markdown 生成、pytest による軽量テストが素直で、MVP の読み取り中心 CLI と相性がよいためです。

Node.js は npm 配布や JavaScript/TypeScript 周辺との統合に強い一方、今回の MVP ではビルドやパッケージ周りの判断が少し増えます。最初は Python で小さく作り、将来 npm 配布やエディタ連携が必要になった時に再検討します。

## 後で決めること

- `reports/` ディレクトリを自動作成するか、保存オプション指定時だけ作るか。
- レポート保存オプションの具体名。
- `last_reviewed` / `next_review` を将来必須にするか。
- `.project-agent.yml` の schema と validation の厳しさ。
- `DECISIONS.md` を標準テンプレートとして含めるか。
- `docs/decisions/` へ移行する条件。
- README と docs の意味的なズレを LLM review でどこまで扱うか。
- 足場キーワード検知が概念説明文に反応しすぎる場合の除外パスや文脈フィルタ。
- `pma before-commit`、`pma after-work`、`pma init`、`pma pause`、`pma resume` などの追加コマンド。
