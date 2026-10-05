# 公開概念体系と役割の言い方

- Status: accepted
- Date: 2026-08-06
- Decision owner: Owner
- Applies to: Ashiba、Keep the Ashiba、Steward、Project Steward Agentの概念上の関係と、公開文書での役割説明
- Does not decide: 公開project・repository・package・organization・domainの改名、商標上の使用可能性、移行時期
- Later decision: 2026-08-16の[正式名称と識別子移行の方針](2026-08-16-public-name-direction.md)で`Ashiba Steward`をプロジェクト全体の正式名称とした。旧称は物理識別子と履歴に限って残し、実識別子の改名と公開は引き続き未実施。

## Context

2026-08-02の[Stewardの役割族・配置・内部呼称](2026-08-02-steward-role-placement.md)は、Stewardを二配置に共通する役割族、Butler / Caddieを内部呼称、Agentをruntimeとして確定しました。一方、全体の公開名称と、二配置を公開文書で何と呼ぶかは未決でした。

2026-08-04にpilotの固定評価を閉じ、MVP hardeningを完了としました。Owner、Claude、Codexの検討では、次が一致しました。

- 取り組みの中核はAgentという一実装ではなく、文脈が失われやすい時を見分け、薄く残し、痕跡から戻し、正本へつなぎ、閉じる知識と実践である。
- `Owner Steward`はOwner自身がStewardであると読まれ得る。
- `Project Steward`を一配置の正式名にすると、現行名`Project Steward Agent`がその配置だけのruntimeと読まれ得る。
- accepted decisionで形容詞の対をやめ、`attached_to`という配置関係を採用したため、公開層でも新しい複合役割名を必須にする理由はない。

Ownerは会話の中で、全体を指す語として`KTA`より`Ashiba`を自然に使用してきました。ただし、これは商標clearanceや第三者利用者テストの代替ではありません。

## Decision

### 1. Ashiba

**Ashiba**を、全体を包含する概念とします。

Ashibaは、再開、引き継ぎ、判断理由の説明、変更前後への復帰を可能にする足がかりであり、次を包含します。

- 文脈喪失のタイミングと回復パターン。
- Keep the Ashibaという方法と実践。
- Stewardという役割族。
- Agent、Skill、CLI、人間の手順などのruntimeとadapter。

これは`ASHIBA`を公開project名または商標として使用できるという判断ではありません。

### 2. Keep the Ashiba

**Keep the Ashiba（KTA）**を、Ashibaを使える状態に保つ方法・考え方・実践の名称とします。

`Ashiba`と`KTA`は競合候補ではありません。Ashibaが全体概念、KTAがそこで行う実践です。

### 3. Steward

公開上、覚える役割族名は**Steward**一語とします。

`Owner Steward`と`Project Steward`を、二配置の正式な公開役割名として採用しません。公開文書では関係をそのまま説明します。

> KTAには、オーナー付きStewardと個別プロジェクト付きStewardの二つの配置があります。

図、表、設定など短い識別が必要な場所では、既存の関係表現を使います。

```yaml
steward:
  attached_to: owner
```

```yaml
steward:
  attached_to: project
```

### 4. Butler / Caddie

オーナー付きStewardの**Butler**、個別プロジェクト付きStewardの**Caddie**は、内部呼称として維持します。

公開文書で必要な場合は、「内部ではそれぞれをButler、Caddieと呼んでいる」と説明できます。単独の公開製品名、package名、organization名にはしません。

### 5. Project Steward Agent / pma

**Project Steward Agent**は、当面、現行repository、Agent runtimeを中心とする実装project、既存公開物と履歴を指す名称として残します。Ashiba全体を恒久的に代表する公開名称として確定したものではありません。

`pma`はPSA全体ではなく、`scan`や`followups`を提供する補助センサーです。

### 6. 公開改名は未決

この節は2026-08-06時点の判断です。2026-08-16の後続判断で公開名称の採用方針は`Ashiba Steward`に確定しましたが、以下の確認を要する実改名は引き続き未決です。

公開project、repository、package、organization、domainを`Ashiba`等へ変更する判断は行いません。

改名の前に、少なくとも次を別に確認します。

- umbrella / project nameとしての`ASHIBA`と`KEEP THE ASHIBA`のclearance。
- 既存v0.2、repository、package、CLI、履歴からの移行方法。
- local Gitで確認できていない公開remote、tag、公開commitの実態。
- 必要に応じた第三者の理解確認。

未調査、取得不能、完全一致なしを「空き」「問題なし」「安全」と解釈しません。

## Consequences

- 公開概念体系は、`Ashiba` > `Keep the Ashiba` > `Steward` > runtime / adapterとして説明できます。
- 二配置を説明するための公開複合役割名を増やしません。
- 利用者向けには「オーナー付きSteward」「個別プロジェクト付きSteward」と短く説明します。これは別々の正式役割名を増やすものではなく、Stewardの配置関係を示す表現です。
- `Project Steward Agent`という現行名と、Bだけを指す`Project Steward`という新語の構文衝突を発生させません。
- 現行のrepository slug、package、CLI、ファイルpathは変更しません。
- 既存の調査、提案、過去の公開物に現れる旧表現は履歴として残し、現行判断への導線を追加します。
- 公開改名を行う場合は、別のaccepted decisionとしてclosure gateを通します。

## Alternatives not adopted

| Alternative | Reason |
|---|---|
| `Owner Steward` / `Project Steward`を正式な公開役割名にする | 前者はOwner本人との曖昧性、後者は現行親名称をBのruntimeと読ませる構文衝突がある |
| `Owner's Steward` / `Project Steward` | 所有格が個人的使用人の印象を強め、二つの新しい公開役割名を必要とする問題も残る |
| `Keep the Ashiba`を全体概念にする | KTAは実践名として既に意味が定まり、Ashibaの方がpattern、method、role、runtimeを包含できる |
| 今すぐ公開名称を`Ashiba`へ変更する | ブランド使用を前提としたclearanceと、既存公開履歴からの移行確認が未完了 |

## Related sources

- [コンセプト](../concept.md)
- [KTA原則](../principles.md)
- [Stewardの役割族・配置・内部呼称](2026-08-02-steward-role-placement.md)
- 公開名称と役割表示の提案（開発資料：`../proposals/2026-08-02-public-name-and-role-labels.md`、本配布では省略）
- 命名クリアランス調査（開発資料：`../research/naming_clearance_2026-07-31.md`、本配布では省略）
- [公開名称の採用方針](2026-08-16-public-name-direction.md)
- [確定判断のclosure gate](2026-08-02-decision-closure-gate.md)
