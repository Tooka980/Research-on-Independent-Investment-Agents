# Research on Independent Investment Agents

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%2B-blue?logo=python" alt="Python">
  <img src="https://img.shields.io/badge/Status-Prototype-orange" alt="Status">
  <img src="https://img.shields.io/badge/Market%20Data-yfinance-lightgrey" alt="Market Data">
  <img src="https://img.shields.io/badge/License-Not%20specified-lightgrey" alt="License">
</p>

<p align="center">
  仮想投資エージェントが市場データ・ニュース・銘柄情報を収集し、分析、仮想注文、リスク確認、パフォーマンス追跡までを行う研究用プロジェクトです。
</p>

---

## 概要

**Research on Independent Investment Agents** は、独立した投資判断エージェントの研究・検証を目的とした Python プロジェクトです。

株価データやニュース情報をもとに、複数のエージェントが銘柄調査、投資判断、仮想注文、リスク評価、成績追跡を行います。実際の売買ではなく、研究・検証・シミュレーションを目的とした仮想投資環境として設計されています。

> [!WARNING]
> このプロジェクトは投資助言や実際の売買指示を目的としたものではありません。表示される判断・注文・分析結果は研究用のシミュレーションであり、実際の投資判断は自己責任で行ってください。

## 主な機能

- yfinance を用いた株価・銘柄情報の取得
- 日本株を中心としたウォッチリスト管理
- 仮想ポートフォリオ・保有銘柄・現金残高の管理
- 仮想注文エージェントによる売買判断
- リスクエージェントによる注文確認
- ニュース・RSS・市場情報を使った調査支援
- 研究組織型エージェントによる分析ワークフロー
- エージェントごとの信頼度・判断パターン・証拠信頼性の記録
- 仮想取引の損益・貢献度・パフォーマンス追跡
- Web ダッシュボードによる確認画面

## 使用技術

| 分類 | 技術 |
|---|---|
| 言語 | Python |
| データ処理 | pandas |
| 市場データ | yfinance |
| Web UI | 標準ライブラリベースの HTTP サーバー |
| 保存先 | JSON / CSV / SQLite / artifacts ディレクトリ |

## ディレクトリ構成

```text
Research-on-Independent-Investment-Agents/
├── src/
│   └── independent_investment_agents/
│       ├── agents/              # 仮想注文・リスク判断エージェント
│       ├── app/                 # Web ダッシュボード起動処理
│       ├── core/                # タスクキュー・共通処理
│       ├── domain/              # 注文・調査タスクなどのドメイン定義
│       ├── performance/         # 成績・貢献度・損益追跡
│       ├── repositories/        # データ保存処理
│       ├── research/            # 調査組織・分析エージェント
│       └── simulation/          # 仮想約定・売買シミュレーション
├── frontend/                    # ダッシュボード用フロントエンド
├── tests/                       # テストコード
├── artifacts/                   # 実行結果・注文・調査ログなどの生成物
├── requirements.txt             # Python 依存関係
└── README.md
```

## セットアップ

### 1. リポジトリをクローン

```bash
git clone https://github.com/Tooka980/Research-on-Independent-Investment-Agents.git
cd Research-on-Independent-Investment-Agents
```

### 2. 仮想環境を作成

```bash
python -m venv .venv
```

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

macOS / Linux:

```bash
source .venv/bin/activate
```

### 3. 依存関係をインストール

```bash
pip install -r requirements.txt
```

### 4. パッケージパスを設定

このリポジトリは `src/` 配下に Python パッケージを配置しているため、直接実行する場合は `PYTHONPATH` を設定してください。

Windows PowerShell:

```powershell
$env:PYTHONPATH = "src"
```

macOS / Linux:

```bash
export PYTHONPATH=src
```

## 起動方法

Web ダッシュボードを起動します。

```bash
python -m independent_investment_agents.app.launch_dashboard
```

ブラウザが自動で開かない場合は、ターミナルに表示された URL をブラウザで開いてください。

## 基本的な使い方

1. ダッシュボードを起動する
2. ウォッチリストや保有銘柄を確認する
3. エージェントが市場データ・ニュース・銘柄情報を収集する
4. 仮想注文エージェントが売買候補を生成する
5. リスクエージェントが注文内容を確認する
6. 仮想約定・損益・判断ログを `artifacts/` に保存する
7. パフォーマンスや判断根拠を確認し、エージェント改善に利用する

## データ保存について

実行結果は主に `artifacts/` 以下に保存されます。

```text
artifacts/
├── live_session/      # セッション情報
├── portfolio/         # ウォッチリスト・保有銘柄・銘柄キュー
├── research/          # 調査結果・SQLite データベース
├── runs/              # 価格データ・プロファイルなど
├── virtual_orders/    # 仮想注文データ
└── performance/       # 損益・貢献度・成績追跡
```

大量の実行ログやキャッシュが含まれる可能性があるため、必要に応じて `.gitignore` で管理してください。

## テスト

テストコードは `tests/` 以下に配置されています。

```bash
python -m pytest
```

`pytest` が入っていない場合は、次のようにインストールしてください。

```bash
pip install pytest
```

## 開発方針

このプロジェクトでは、単一の売買ロジックではなく、複数の専門エージェントが協調して判断する構成を目指しています。

- 情報収集エージェント
- ニュース分析エージェント
- 銘柄探索エージェント
- 売買判断エージェント
- リスク確認エージェント
- パフォーマンス評価エージェント
- 最終承認ゲート

将来的には、より大規模な調査チーム化、安定したニュース分析、エージェント間の役割分担、実売買注文エージェントとの連携を視野に入れています。

## 注意事項

- 本プロジェクトは研究・学習・シミュレーション目的です。
- 実際の金融商品取引を自動実行するものではありません。
- yfinance や外部ニュースソースの取得結果は、通信状況や提供元の仕様変更により失敗する場合があります。
- 生成された分析結果には誤りが含まれる可能性があります。
- 実際の投資判断には、必ず公式情報や複数の信頼できる情報源を確認してください。

## License

ライセンスは未指定です。公開・再利用範囲を明確にする場合は、`LICENSE` ファイルの追加を推奨します。

## Author

- GitHub: [@Tooka980](https://github.com/Tooka980)
