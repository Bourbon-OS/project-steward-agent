# 確定判断のclosure gate

- Status: accepted
- Date: 2026-08-02
- Decision owner: Owner
- Applies to: Ashiba Steward（当時の名称Project Steward Agent）における、正本文書へ影響する確定判断の記録とGit履歴化
- Canonical branch for this repository: `master`

## Context

2026-08-02の命名判断は会話では合意していたものの、最初の記録が、その時たまたま作業中だった別ブランチへcommitされました。

問題は、誤ったブランチを使った一回の操作だけではありません。次の欠陥が同時にありました。

- Ownerの確定判断を受領した時に、チャットから正本へ移す必須triggerがなかった。
- project-localな正本を特定しても、その変更を載せる正規の履歴線を確認していなかった。
- 現在checkoutされているブランチを、根拠なく正規の履歴線として扱った。
- `commit済み`、`masterへ到達済み`、`外部公開済み`を別状態として確認していなかった。

謝罪や注意喚起だけでは同じ欠陥を防げないため、確定判断のclosureを検証可能な手順にします。

## Decision

### 1. 確定判断をeventとして扱う

Ownerが、採用、確定、承認、却下、保留、停止、対象外など、次の扱いを明示した時は`decision-accepted` eventとして扱います。

会話で受領しただけでは閉じません。正本へ影響する場合は、project-localな反映状態を`反映待ち`とします。

### 2. 判断の状態を分ける

少なくとも次を混同しません。

- `proposed`: 検討中で、Ownerがまだ採用していない。
- `accepted`: Ownerが採用した。
- `superseded`: 後の判断で置き換えられた。
- `historical`: 調査、議論、過去時点の証拠として保存するが、現行判断ではない。

外部AIの回答、調査報告、会話中の案を、Ownerの`accepted`判断として扱いません。

### 3. closureに必要な証拠

正本文書へ影響する`accepted`判断は、次の全項目が確認できるまで閉じません。

1. **Canonical record**: 現行判断を読む正本path、または正本への導線がある。
2. **Canonical branch**: Gitを使うprojectでは、正規の履歴線を確認する。現在ブランチを根拠なく代用しない。
3. **Scoped commit**: 判断に関係する対象ファイルだけを明示してstageし、履歴化する。`git add .`は使わない。
4. **Reachability**: commitがcanonical branchから到達できることを確認する。別ブランチにcommitがあるだけでは完了にしない。
5. **Publication state**: `local commit only`、`pushed`、`tagged`、`released`などを区別し、観測できた状態だけを記録する。

Gitを使わないprojectでは、2から4を無理に適用せず、採用されている履歴・変更管理方法で同じ証拠を残します。

### 4. このrepositoryの正規の履歴線

このrepositoryでは、正式な正本文書の確定判断を閉じるcanonical branchを`master`とします。

作業ブランチで判断記録を準備すること自体は禁止しません。ただし、そのcommitが`master`から到達できると確認するまでは`committed off canonical`であり、反映完了とは扱いません。

作業開始時から別ブランチがcheckoutされていても、その事実はOwnerのブランチ選択や公開承認を意味しません。

### 5. commitと公開を分ける

Git commitは履歴化であり、外部公開ではありません。

remote、push先、tag、公開配布物を確認できない場合は`外部公開済み`と表現しません。公開が依頼範囲外または実行不能なら、正本には現在のpublication stateと次の必要作業を残します。

### 6. 事故時の修復

確定判断をcanonical branch以外へcommitした場合は、次の順で修復します。

1. 対象commitと混入してはならない変更を確認する。
2. 判断記録に関係するcommitだけをcanonical branchへ移す。
3. conflictがあれば、canonical branchに存在しない別作業を持ち込まない。
4. canonical branchからの到達、差分、publication stateを再確認する。
5. 誤った履歴線を破壊的に書き換えず、必要性がある場合だけOwnerへ整理案を出す。

## Applied correction

- 最初の命名判断commit: `63ecd9a`（`codex/next-version-due-selector`上。正規の反映先ではない）
- `master`へ移したcommit: `14944aa`
- `master`へ持ち込んだ範囲: 命名判断と、その正本・導線・調査snapshotに関する9ファイル
- 除外した範囲: 元ブランチにあった次期版の実装・試験変更
- Publication state at decision time: `local commit only`

## Consequences

- 「会話で合意した」「ファイルを書いた」「どこかへcommitした」だけでは、確定判断を閉じません。
- Butlerは、確定判断が該当projectのCaddieへ渡り、canonical recordへ反映されたかを追います。
- Caddieは、正本path、canonical branch、commitの到達、publication stateを確認して結果を返します。
- timing-driven reviewは、`反映待ち`、`committed off canonical`、publication stateが不明な確定判断を拾います。
- 自動hookや新しいdaemonは現行pilotへ追加しません。このgateをSkillの必須手順として運用し、再発または手作業負担が観測された場合に機械的検査を次版候補として評価します。

## Related sources

- [KTA原則](../principles.md)
- [Stewardの役割族・配置・内部呼称](2026-08-02-steward-role-placement.md)
- [Ashiba Steward Skill](../../skills/project-steward/SKILL.md)
- [Ashiba Steward 運用ルール](../../skills/project-steward/references/stewardship_rules.md)
