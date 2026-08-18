---
# この1本ぶんの指示。共通の既定は gmp.toml にある:
#   C:\Repos\mywork\GhostMoviePlay\gmp.toml
# いま効いている値と由来: gmp config docs/video/intro/video.md
title: GhostMoviePlay とは

scenes:
  - id: why
    goal: 素朴に AI へ操作させると観られない動画になる、という問題を出す
  - id: passes
    goal: AI を使う段を 1 つに閉じ込める 3 段構成を、箱を指しながら説明する
  - id: plan
    goal: 台本 plan.json が人の手で直せることを見せる
  - id: settings
    goal: 設定の 3 層と、設定画面が層を選んでから編集する形になっていることを見せる
  - id: output
    goal: 出来上がりと、この動画自体がこのツールで作られていることを言う
---

## 補足

- 収録対象は自分自身の説明ページ（`site/index.html`）。このツールでこのツールを説明する。
- 各 section は 1280x720 にちょうど収まる高さにしてある。`scroll_to` で送り、
  `highlight` で指しながら喋る。**操作の速さより、字幕を読み切れることを優先する。**
- 最後の 1 ビートで「この動画も GhostMoviePlay で撮っています」と言い切る。
