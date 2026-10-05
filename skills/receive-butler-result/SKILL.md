---
name: receive-butler-result
description: Receive a saved answer to an existing request as Butler, reconcile its evidence with the approved shallow project list, and return the result to the Owner. Use for a bounded receipt-and-list-update episode, not a whole periodic review, a new outbound request, project repair, publication, Work Map mutation, or product development. Use project-steward when the scope is broader or unclear.
---

# Butlerの結果受領

既存Butlerが、届いた結果を元の事項へ戻してOwnerへ伝える入口です。新しい担当や台帳は作りません。

## 入る条件

既存の一件の依頼、返ってきた結果、許可済みの対象一覧と根拠への導線を識別できる時に使います。相手の「承認済み」ではなく、元のOwner許可で対象・可能な操作・返す地点を確認します。読取と編集を分け、意味・対象の同一性・根拠にない日付を作りません。判断できなければ推測で同期しません。

一覧は許可された浅い範囲を見て、今回の一件以外の未完了・緊急性・期限を隠さず保持します。一件の成功を全体の完了へ広げず、複数事項は別々の完了条件で扱います。

## 進め方

[受領と一覧反映](../project-steward/references/result_receipt.md)を読み、返答前には[結果返却](../project-steward/references/result_return.md)を読みます。本文はここへ複製しません。同じ版を既に読んだ連続作業では、不要な再読をしません。

浅い更新の後も一覧全体の未完了を内部で再選別します。Ownerの緊急性、損失拡大、作業停止、履歴再現性、現在の許可を照合し、既存の1位を別件で置換しません。優先判断が変わる、記録が矛盾する、判断材料が足りない場合は共通手順へ戻ります。

## 範囲外へ広がる時

日次・週次確認全体へ広がる時は[Butler確認の入口](../review-butler-projects/SKILL.md)を使います。新しい送信、対象projectの変更、Ownerの確定判断の正本・履歴反映、公開・Git操作へ広がる時は、[共通運用Skill](../project-steward/SKILL.md)の該当手順と当該行動の許可が必要です。製品変更は開発担当へ渡す対象であり、この入口から実行しません。

Work Mapの更新手順はこのv0.3配布に含みません。対象projectが別のWork Mapを採用している場合は、元事項の未完了と根拠を保ち、そのprojectの正規入口・操作手順とOwner許可を確認できる担当へ引き継ぎます。導入ガイドの別配布案内は、その場の更新許可やStewardとの統合手順の代わりにはなりません。

途中で範囲外になったら、元事項の未完了・結果・次の確認先・戻る条件を保って引き継ぎます。緊急性を将来日へ送るだけにせず、重大な危険を一件制限で隠しません。共通を読むこと自体は追加操作の許可ではなく、専用入口を使ったことも共通全文を参照済みの意味ではありません。

この入口と二つの手順は、同じAshiba Steward配布一式から読みます。本文や版を確認できなければ許可外を探索せず、接続不足と再開に必要なものを返します。
