"""設定画面のうち、ウィンドウを作らずに決まる部分.

行の作り方・書込先の選び方・保存する値の作り方はモジュール関数にしてある。
tkinter を起動しないので CI でも走る。
"""

import tomllib

import pytest

from ghostmovieplay import settings, ui


# --- タブの割り当て ---------------------------------------------------
def test_every_setting_appears_in_exactly_one_tab():
    """設定を足したのに画面から漏れる、を防ぐ."""
    placed = [key for tab in ui.TABS for key in tab.keys]
    assert sorted(placed) == sorted(settings.SETTINGS)
    assert len(placed) == len(set(placed)), "2 つのタブに出ている項目がある"


def test_a_row_only_holds_settings_with_the_same_layers():
    """行はまとめて出し分ける. 書ける層が違うものを並べると片方が宙に浮く."""
    for tab in ui.TABS:
        for group in tab.groups:
            for row in group.rows:
                layers = {settings.SETTINGS[p].layers for p in row.paths}
                assert len(layers) == 1, f"{tab.title}/{row.label}: {row.paths}"


def test_rarely_changed_groups_start_folded():
    folded = [g.title for t in ui.TABS for g in t.groups if g.collapsed]
    assert folded, "畳む区切りが 1 つも無い"
    # 畳んだ中に、よく変えるものを入れていないこと
    hidden = {p for t in ui.TABS for g in t.groups if g.collapsed for p in
              (x for r in g.rows for x in r.paths)}
    for key in ("voice.speaker", "app.url", "persona.style", "series.audience"):
        assert key not in hidden, f"{key} を畳んではいけない"


def test_every_group_and_row_has_a_label():
    for tab in ui.TABS:
        assert tab.groups
        for group in tab.groups:
            assert group.title and group.rows
            for row in group.rows:
                assert row.label and row.fields


def test_rows_that_cannot_be_written_are_hidden():
    """gmp.toml を作る前に「入力できない入力欄」を並べない."""
    url = ui.Row("URL", (ui.Field("app.url"),))
    assert ui.visible(url, settings.PROJECT, has_project=True, pinned=set())
    assert not ui.visible(url, settings.PROJECT, has_project=False, pinned=set())
    # グローバル設定を編集しているときは、そもそも置けないので出さない
    assert not ui.visible(url, settings.MACHINE, has_project=True, pinned=set())


def test_effective_values_stay_visible_even_when_unwritable():
    """直せなくても「いまこうなっている」は見せる (video.md の上書きなど)."""
    title = ui.Row("動画タイトル", (ui.Field("title"),))
    assert not ui.visible(title, settings.PROJECT, has_project=True, pinned=set())
    assert ui.visible(title, settings.PROJECT, has_project=True, pinned={"title"})


def test_machine_settings_show_without_a_project_file():
    font = ui.Row("字幕フォント", (ui.Field("render.font"),))
    assert ui.visible(font, settings.MACHINE, has_project=False, pinned=set())
    assert not ui.visible(font, settings.PROJECT, has_project=True, pinned=set())


def test_machine_tab_holds_exactly_the_runtime_settings():
    machine = next(tab for tab in ui.TABS if tab.title == "出力とツール")
    runtime = {s.path for s in settings.SCHEMA if s.bake == "runtime"}
    assert set(machine.keys) == runtime


# --- 編集対象 ---------------------------------------------------------
def test_project_facts_can_only_be_set_on_the_project():
    assert ui.settable("app.url", settings.PROJECT, has_project=True)
    assert not ui.settable("app.url", settings.MACHINE, has_project=True)
    assert not ui.settable("determinism.seed", settings.MACHINE, has_project=True)


def test_runtime_settings_can_only_be_set_on_the_machine():
    assert ui.settable("render.font", settings.MACHINE, has_project=True)
    assert not ui.settable("render.font", settings.PROJECT, has_project=True)


def test_nothing_is_settable_on_a_project_without_a_file():
    assert not ui.settable("voice.speaker", settings.PROJECT, has_project=False)
    assert ui.settable("voice.speaker", settings.MACHINE, has_project=False)


def test_the_editing_layer_is_not_chosen_per_row():
    """行ごとに書込先を選ばせると、グローバル設定を意図せず書き換える."""
    assert set(ui.EDITABLE) == {settings.PROJECT, settings.MACHINE}
    assert settings.VIDEO not in ui.EDITABLE      # video.md は UI から書かない


# --- 再合成の警告 -----------------------------------------------------
def test_audio_affecting_settings_are_marked():
    assert ui.affects_audio("voice.speed")
    assert ui.affects_audio("voice.speaker")
    assert not ui.affects_audio("voice.url")      # NON_AUDIO_KEYS
    assert not ui.affects_audio("persona.style")  # 文面であって音ではない


# --- 読み辞書のテキスト ------------------------------------------------
def test_dictionary_text_round_trips():
    entries = {"語": "ゴ", "冪等": {"pronunciation": "ベキトウ", "accent": 1}}
    text = ui.format_dict_text(entries)
    assert text.splitlines()[0] == "語 = ゴ"
    assert ui.parse_dict_text(text) == entries


def test_accent_zero_survives_the_round_trip():
    """0 は「頭高」という意味のある値. falsy だからと落とすと画面で消える."""
    entries = {"冪等": {"pronunciation": "ベキトウ", "accent": 0}}
    assert ui.parse_dict_text(ui.format_dict_text(entries)) == entries


def test_dictionary_text_keeps_the_accent():
    assert ui.parse_dict_text("冪等 = ベキトウ, 1") == {
        "冪等": {"pronunciation": "ベキトウ", "accent": 1}
    }


def test_broken_dictionary_lines_are_reported_with_a_line_number():
    with pytest.raises(settings.SettingsError, match="2 行目"):
        ui.parse_dict_text("語 = ゴ\nこわれた行\n")
    with pytest.raises(settings.SettingsError, match="1 行目"):
        ui.parse_dict_text("語 = \n")


def test_dictionary_ignores_blank_and_comment_lines():
    assert ui.parse_dict_text("\n# めも\n語 = ゴ\n") == {"語": "ゴ"}


# --- 撮る対象のフォルダ (名前 = 値 だけの表) --------------------------
def test_project_folders_keep_a_comma_in_the_path():
    """アクセントとして読むと、コンマを含むフォルダが保存できない."""
    assert ui.parse_dict_text("a-lamo = C:/Repos/a, b", accents=False) == {
        "a-lamo": "C:/Repos/a, b"
    }


# --- 保存する値を決める -----------------------------------------------
def edit(path, text, original="", target=settings.PROJECT):
    return ui.Edit(path=path, text=text, original=original, target=target)


def test_only_changed_rows_are_written():
    writes = ui.plan_writes([
        edit("voice.speaker", "ずんだもん", original="ずんだもん"),
        edit("voice.speed", "1.2", original="1.0"),
    ])
    assert writes == {settings.PROJECT: {"voice.speed": 1.2}}


def test_values_are_typed_by_the_schema():
    writes = ui.plan_writes([
        edit("render.crf", "18", target=settings.MACHINE),
        edit("series.topics", "基本操作, 設定", target=settings.PROJECT),
    ])
    assert writes[settings.MACHINE]["render.crf"] == 18
    assert writes[settings.PROJECT]["series.topics"] == ["基本操作", "設定"]


def test_emptying_a_row_removes_the_value():
    writes = ui.plan_writes([edit("voice.style", "", original="ノーマル")])
    assert writes[settings.PROJECT]["voice.style"] is None


def test_a_row_with_nowhere_to_go_is_an_error():
    with pytest.raises(settings.SettingsError, match="保存先がありません"):
        ui.plan_writes([edit("app.url", "http://x", target="")])


def test_writing_to_the_wrong_layer_is_refused():
    """グローバル設定に app.url を書こうとしたら、黙って捨てずに止める."""
    with pytest.raises(settings.SettingsError, match="app.url"):
        ui.plan_writes([edit("app.url", "http://x", target=settings.MACHINE)])


def test_a_bad_value_names_the_setting():
    with pytest.raises(settings.SettingsError, match="video.fps"):
        ui.plan_writes([edit("video.fps", "はやい")])


def test_dictionary_edits_go_through_as_a_table():
    writes = ui.plan_writes([edit("voice.dict", "語 = ゴ", original="")])
    assert writes[settings.PROJECT]["voice.dict"] == {"語": "ゴ"}


def test_project_folders_are_saved_without_accents():
    """撮る対象の登録は `名前 = フォルダ` だけ. アクセントとして割らない."""
    writes = ui.plan_writes([
        edit("projects", "a-lamo = C:/Repos/a, b", target=settings.MACHINE),
    ])
    assert writes[settings.MACHINE]["projects"] == {"a-lamo": "C:/Repos/a, b"}


# --- 実際に書く -------------------------------------------------------
def test_save_writes_both_layers(tmp_path, monkeypatch):
    cfg = tmp_path / "config.toml"
    project = tmp_path / settings.PROJECT_FILE
    project.write_text("# 手で書いたコメント\nproject = 'X'\n", encoding="utf-8")
    monkeypatch.setattr(ui.paths, "config_path", lambda: cfg)

    written = ui.save(
        {
            settings.MACHINE: {"render.font": "Meiryo"},
            settings.PROJECT: {"voice.speaker": "ずんだもん"},
        },
        project,
    )

    assert len(written) == 2
    assert tomllib.loads(cfg.read_text(encoding="utf-8"))["render"]["font"] == "Meiryo"
    text = project.read_text(encoding="utf-8")
    assert "# 手で書いたコメント" in text          # 人の書いたものを壊さない
    assert tomllib.loads(text)["voice"]["speaker"] == "ずんだもん"


def test_save_without_a_project_file_is_an_error():
    with pytest.raises(settings.SettingsError):
        ui.save({settings.PROJECT: {"voice.speaker": "x"}}, None)


# --- ウィンドウが要るぶん (画面が無ければ飛ばす) -----------------------
# tk_root (セッションに 1 つだけの Tk) は tests/conftest.py にある
@pytest.fixture
def window(tk_root, tmp_path, monkeypatch):
    import tkinter as tk

    # 話者の取得は起動時に走る。テストでは ENGINE を叩かせない
    monkeypatch.setattr(ui.SettingsPane, "_load_speakers_async", lambda self: None)
    top = tk.Toplevel(tk_root)
    top.withdraw()
    made = ui.SettingsPane(top, ui.AppState())
    # 開いた場所 (カレント) の gmp.toml に左右されないよう、空の場所へ移す
    made.project_dir.set(str(tmp_path))
    made.reload()
    yield made
    top.destroy()


def test_speaker_list_survives_a_reload(window, tmp_path):
    """プロジェクトを選び直すと行を作り直す. 話者一覧を入れ直さないと空になる."""
    window.create_project_file()      # 声の行が出るようにする
    window.speakers = [{"name": "ずんだもん", "styles": [{"name": "ノーマル"}]}]
    window.reload()

    assert list(window.speaker_box["values"]) == ["ずんだもん"]

    window.speaker_box.set("ずんだもん")
    window._refresh_styles()
    assert list(window.style_box["values"]) == ["ノーマル"]


def test_project_form_appears_only_after_the_file_is_made(window, tmp_path, monkeypatch):
    """作る前は収録対象のフォームを出さず、作ると出る."""
    def titles() -> list[str]:
        body = window.frames["対象と動画"]
        return [
            child.winfo_children()[1].cget("text")
            for child in body.winfo_children()
            if child.winfo_children()
            and child.winfo_children()[0].cget("text") in ("▼", "▶")
        ]

    assert "収録対象" not in titles()
    assert "app.url" not in window.rows

    window.create_project_file()

    assert (tmp_path / settings.PROJECT_FILE).is_file()
    assert "収録対象" in titles()
    assert "app.url" in window.rows


def test_deleting_the_project_file_needs_a_yes(window, tmp_path, monkeypatch):
    window.create_project_file()
    target = tmp_path / settings.PROJECT_FILE

    monkeypatch.setattr(ui.messagebox, "askyesno", lambda *a, **k: False)
    window.delete_project_file()
    assert target.is_file(), "訊いて No なのに消してはいけない"

    monkeypatch.setattr(ui.messagebox, "askyesno", lambda *a, **k: True)
    window.delete_project_file()
    assert not target.exists()
    assert "app.url" not in window.rows     # フォームも一緒に引っ込む


def test_editing_a_project_never_touches_the_machine_default(window, tmp_path, monkeypatch):
    """グローバル設定から来ている値を直しても、書き先はプロジェクトのまま.

    ここが行ごとの選択だったころは、既定 (= 全プロジェクト) を書き換えていた。
    """
    cfg = tmp_path / "config.toml"
    monkeypatch.setattr(ui.paths, "config_path", lambda: cfg)
    ui.paths.save_config({"voice": {"speaker": "ずんだもん"}})   # グローバル設定
    window.create_project_file()

    assert window.resolved.origin("voice.speaker").layer == settings.PROJECT
    window.rows["voice.speaker"]["getter"] = lambda: "波音リツ"
    writes = ui.plan_writes(window.edits())

    assert writes == {settings.PROJECT: {"voice.speaker": "波音リツ"}}
    assert settings.MACHINE not in writes


def test_machine_mode_hides_project_only_settings(window):
    window.create_project_file()
    assert "app.url" in window.rows

    window.layer.set(settings.MACHINE)
    window.reload()

    assert "app.url" not in window.rows          # グローバル設定には置けない
    assert "render.font" in window.rows
    assert window.rows["render.font"]["target"] == settings.MACHINE


def test_reload_keeps_folded_groups_folded(window):
    window.create_project_file()
    key = ("声と口調", ui.RARELY)
    assert window.folded[key] is True
    window.folded[key] = False
    window.reload()
    assert window.folded[key] is False
