import io

import polars as pl
import pytest

import drive


class FakeRequest:
    def __init__(self, result=None, error=None):
        self._result = result
        self._error = error

    def execute(self):
        if self._error:
            raise self._error
        return self._result


class FakeFiles:
    def __init__(self, existing_id=None, content=b"", list_error=None):
        self.existing_id = existing_id
        self.content = content
        self.list_error = list_error
        self.calls = []

    def list(self, **kwargs):
        self.calls.append(("list", kwargs))
        files = [{"id": self.existing_id}] if self.existing_id else []
        return FakeRequest({"files": files}, self.list_error)

    def update(self, **kwargs):
        self.calls.append(("update", kwargs))
        return FakeRequest({"id": kwargs["fileId"]})

    def create(self, **kwargs):
        self.calls.append(("create", kwargs))
        return FakeRequest({"id": "nouveau-fichier"})

    def get_media(self, fileId):
        self.calls.append(("get_media", fileId))
        return self.content


class FakeService:
    def __init__(self, **kwargs):
        self._files = FakeFiles(**kwargs)

    def files(self):
        return self._files


class FakeDownloader:
    def __init__(self, fh, content):
        fh.write(content)

    def next_chunk(self):
        return None, True


@pytest.fixture(autouse=True)
def folder(monkeypatch):
    monkeypatch.setenv("DRIVE_FOLDER_ID", "dossier-test")
    monkeypatch.setattr(drive, "MediaIoBaseUpload", lambda buffer, **kw: buffer)
    monkeypatch.setattr(drive, "MediaIoBaseDownload", FakeDownloader)


DF = pl.DataFrame({"date": ["2026-01-01"], "montant": [-1.0]})


def test_creation_si_fichier_absent():
    service = FakeService()
    outcome = drive.save_to_drive(service, DF)
    assert outcome.status == "success"
    assert outcome.file_id == "nouveau-fichier"
    assert [c[0] for c in service.files().calls] == ["list", "create"]


def test_mise_a_jour_si_fichier_present():
    service = FakeService(existing_id="f123")
    outcome = drive.save_to_drive(service, DF)
    assert outcome.file_id == "f123"
    assert "f123" in outcome.message
    assert [c[0] for c in service.files().calls] == ["list", "update"]


def test_requete_echappe_les_apostrophes():
    service = FakeService()
    drive.find_file_id(service, "l'export.csv", "dossier")
    query = service.files().calls[0][1]["q"]
    assert "name='l\\'export.csv'" in query


def test_chargement_csv():
    csv = io.BytesIO()
    DF.write_csv(csv)
    service = FakeService(existing_id="f123", content=csv.getvalue())
    outcome = drive.load_from_drive(service)
    assert outcome.df.to_dicts() == DF.to_dicts()


def test_fichier_absent_donne_un_avertissement():
    outcome = drive.load_from_drive(FakeService())
    assert outcome.status == "warning"
    assert outcome.df is None


def test_erreur_api_capturee():
    outcome = drive.load_from_drive(FakeService(list_error=RuntimeError("quota")))
    assert outcome.status == "error"
    assert "quota" in outcome.message


def test_dossier_non_configure(monkeypatch):
    monkeypatch.delenv("DRIVE_FOLDER_ID")
    outcome = drive.save_to_drive(FakeService(), DF)
    assert outcome.status == "error"
    assert "DRIVE_FOLDER_ID" in outcome.message
