import base64
from pathlib import Path

import pytest

from src import cli as cli_module


class DummyToolInput:
    """Simple stand-in object for ToolInput in tests."""

    def __init__(self, payload: dict) -> None:
        self.payload = payload


class DummyToolResponse:
    """Simple stand-in object for ToolResponse in tests."""

    def __init__(self, success: bool, transcription: str = "", error: str | None = None) -> None:
        self.success = success
        self.transcription = transcription
        self.error = error


class DummyTranscribeAudioTool:
    """
    Fake TranscribeAudioTool used for testing.

    It records the last arguments it received and returns
    a predefined response.
    """

    def __init__(self, response: DummyToolResponse) -> None:
        self._response = response
        self.last_arguments: dict | None = None

    def validate_input(self, arguments: dict) -> DummyToolInput:
        self.last_arguments = arguments
        return DummyToolInput(arguments)

    def execute(self, tool_input: DummyToolInput, invocation_id: str | None = None) -> DummyToolResponse:
        # Ensure the same payload flows through.
        assert tool_input.payload == self.last_arguments
        return self._response


def test_run_cli_success(tmp_path, monkeypatch):
    """CLI writes transcription text file on successful transcription."""
    media_path = tmp_path / "input.ogg"
    media_bytes = b"fake-audio-bytes"
    media_path.write_bytes(media_bytes)

    # Prepare dummy tool that reports success.
    response = DummyToolResponse(success=True, transcription="hello world")
    dummy_tool = DummyTranscribeAudioTool(response=response)

    # Patch TranscribeAudioTool in the cli module to return our dummy.
    def fake_transcribe_audio_tool(*args, **kwargs):
        return dummy_tool

    monkeypatch.setattr(cli_module, "TranscribeAudioTool", fake_transcribe_audio_tool)

    output_base = tmp_path / "out" / "my_new"

    exit_code = cli_module.run_cli(media_path, output_base, stdout_mode=False)

    assert exit_code == 0
    output_path = output_base.with_suffix(".txt")
    assert output_path.exists()
    assert output_path.read_text(encoding="utf-8") == "hello world"

    # Verify the tool saw base64-encoded audio data.
    assert dummy_tool.last_arguments is not None
    encoded = dummy_tool.last_arguments["audio_data"]
    assert isinstance(encoded, str)
    assert base64.b64decode(encoded.encode("utf-8")) == media_bytes


def test_run_cli_tool_failure(tmp_path, monkeypatch, capsys):
    """CLI returns non-zero and does not write output on tool failure."""
    media_path = tmp_path / "input.ogg"
    media_path.write_bytes(b"fake-audio-bytes")

    response = DummyToolResponse(success=False, error="some error")
    dummy_tool = DummyTranscribeAudioTool(response=response)

    def fake_transcribe_audio_tool(*args, **kwargs):
        return dummy_tool

    monkeypatch.setattr(cli_module, "TranscribeAudioTool", fake_transcribe_audio_tool)

    output_base = tmp_path / "out" / "my_new"

    exit_code = cli_module.run_cli(media_path, output_base, stdout_mode=False)
    captured = capsys.readouterr()

    assert exit_code != 0
    assert "Transcription error" in captured.err

    output_path = output_base.with_suffix(".txt")
    assert not output_path.exists()


def test_run_cli_no_speech_success(tmp_path, monkeypatch):
    """
    When transcription succeeds but has no speech (empty text),
    CLI should still succeed and create an empty file.
    """
    media_path = tmp_path / "input.ogg"
    media_path.write_bytes(b"fake-audio-bytes")

    response = DummyToolResponse(success=True, transcription="")
    dummy_tool = DummyTranscribeAudioTool(response=response)

    def fake_transcribe_audio_tool(*args, **kwargs):
        return dummy_tool

    monkeypatch.setattr(cli_module, "TranscribeAudioTool", fake_transcribe_audio_tool)

    output_base = tmp_path / "out" / "my_new"

    exit_code = cli_module.run_cli(media_path, output_base, stdout_mode=False)

    assert exit_code == 0
    output_path = output_base.with_suffix(".txt")
    assert output_path.exists()
    assert output_path.read_text(encoding="utf-8") == ""


def test_run_cli_missing_input_file(tmp_path, capsys):
    """Missing input file should result in non-zero exit and no output file."""
    media_path = tmp_path / "does_not_exist.ogg"
    output_base = tmp_path / "out" / "my_new"

    exit_code = cli_module.run_cli(media_path, output_base, stdout_mode=False)
    captured = capsys.readouterr()

    assert exit_code != 0
    assert "Input file does not exist" in captured.err

    output_path = output_base.with_suffix(".txt")
    assert not output_path.exists()


def test_cli_argparse_missing_arguments(capsys):
    """
    Calling cli() with missing mediaPath should result in SystemExit from argparse.
    This tests the argument parsing layer without touching the filesystem.
    """
    with pytest.raises(SystemExit) as excinfo:
        cli_module.cli(argv=[])

    assert excinfo.value.code != 0
    captured = capsys.readouterr()
    # argparse typically prints usage information to stderr.
    assert "usage:" in captured.err


def test_cli_argparse_stdout_without_outputbase(tmp_path, monkeypatch, capsys):
    """When --stdout is used, outputBase is optional and not required."""
    media_path = tmp_path / "input.ogg"
    media_path.write_bytes(b"fake-audio-bytes")

    response = DummyToolResponse(success=True, transcription="test output")
    dummy_tool = DummyTranscribeAudioTool(response=response)

    def fake_transcribe_audio_tool(*args, **kwargs):
        return dummy_tool

    monkeypatch.setattr(cli_module, "TranscribeAudioTool", fake_transcribe_audio_tool)

    # Call cli() with --stdout but no outputBase
    exit_code = cli_module.cli(argv=[str(media_path), "--stdout"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.out == "test output"
    # stderr should contain log file location message, but no actual log output
    assert "Logging to file:" in captured.err


def test_cli_argparse_no_stdout_missing_outputbase(capsys):
    """When --stdout is not used, outputBase is required."""
    with pytest.raises(SystemExit) as excinfo:
        # Only provide mediaPath, missing outputBase
        cli_module.cli(argv=["/tmp/test.ogg"])

    assert excinfo.value.code != 0
    captured = capsys.readouterr()
    assert "outputBase is required when --stdout is not specified" in captured.err


def test_cli_argparse_stdout_with_outputbase_ignored(tmp_path, monkeypatch, capsys):
    """When --stdout is used, outputBase can be provided but is ignored."""
    media_path = tmp_path / "input.ogg"
    media_path.write_bytes(b"fake-audio-bytes")

    response = DummyToolResponse(success=True, transcription="test output")
    dummy_tool = DummyTranscribeAudioTool(response=response)

    def fake_transcribe_audio_tool(*args, **kwargs):
        return dummy_tool

    monkeypatch.setattr(cli_module, "TranscribeAudioTool", fake_transcribe_audio_tool)

    # Call cli() with --stdout and outputBase (should be ignored)
    output_base = tmp_path / "ignored" / "output"
    exit_code = cli_module.cli(argv=[str(media_path), str(output_base), "--stdout"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.out == "test output"
    # stderr should contain log file location message when --stdout is used
    assert "Logging to file:" in captured.err
    # Verify no file was created
    assert not output_base.with_suffix(".txt").exists()


def test_run_cli_stdout_mode_writes_to_stdout_only(tmp_path, monkeypatch, capsys):
    """When --stdout mode is used, write transcription to stdout and no file."""
    media_path = tmp_path / "input.ogg"
    media_bytes = b"fake-audio-bytes"
    media_path.write_bytes(media_bytes)

    response = DummyToolResponse(success=True, transcription="hello from stdout")
    dummy_tool = DummyTranscribeAudioTool(response=response)

    def fake_transcribe_audio_tool(*args, **kwargs):
        return dummy_tool

    monkeypatch.setattr(cli_module, "TranscribeAudioTool", fake_transcribe_audio_tool)

    # In stdout mode, output_base can be None
    exit_code = cli_module.run_cli(media_path, output_base=None, stdout_mode=True)
    captured = capsys.readouterr()

    assert exit_code == 0
    # Transcription should go to stdout only.
    assert captured.out == "hello from stdout"
    # stderr should be empty (logging goes to file, not stderr)
    assert captured.err == ""


def test_cli_stdout_mode_logs_to_file(tmp_path, monkeypatch, capsys):
    """When --stdout is used, verify logging goes to file and stdout stays clean."""
    import tempfile
    from pathlib import Path
    
    media_path = tmp_path / "input.ogg"
    media_path.write_bytes(b"fake-audio-bytes")

    response = DummyToolResponse(success=True, transcription="test transcription")
    dummy_tool = DummyTranscribeAudioTool(response=response)

    def fake_transcribe_audio_tool(*args, **kwargs):
        return dummy_tool

    monkeypatch.setattr(cli_module, "TranscribeAudioTool", fake_transcribe_audio_tool)

    # Use a known temp directory for log file
    with monkeypatch.context() as m:
        # Patch get_stdout_mode_log_path to use our test directory
        test_log_path = tmp_path / "test_cli.log"
        m.setattr(
            cli_module,
            "get_stdout_mode_log_path",
            lambda: test_log_path
        )
        
        exit_code = cli_module.cli(argv=[str(media_path), "--stdout"])
        captured = capsys.readouterr()

        assert exit_code == 0
        # Transcription should be in stdout
        assert captured.out == "test transcription"
        # Log file location message should be in stderr
        assert "Logging to file:" in captured.err
        assert str(test_log_path) in captured.err
        
        # Verify log file was created and contains log entries
        assert test_log_path.exists()
        log_content = test_log_path.read_text(encoding="utf-8")
        # Log file should contain some log entries (exact content depends on logging format)
        assert len(log_content) > 0

