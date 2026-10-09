"""Turno de GPU entre la IA y el OCR (equipos con una GPU pequeña)."""
import fcntl
import tempfile
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase

from motor import gpu_turno


class TurnoGpuTests(SimpleTestCase):
    def test_apagado_no_hace_nada(self):
        with mock.patch.object(gpu_turno, "GPU_COMPARTIDA", False), mock.patch.object(gpu_turno.requests, "post") as post:
            with gpu_turno.turno_ia():
                pass
        post.assert_not_called()

    def test_encendido_toma_el_turno_y_pide_la_gpu_al_ocr(self):
        with tempfile.TemporaryDirectory() as tmp:
            candado = Path(tmp) / "gpu.lock"
            with mock.patch.object(gpu_turno, "GPU_COMPARTIDA", True), mock.patch.object(gpu_turno, "CANDADO", candado), \
                    mock.patch.object(gpu_turno.requests, "post") as post, \
                    mock.patch.object(gpu_turno.requests, "get", side_effect=gpu_turno.requests.ConnectionError("sin ollama")):
                with gpu_turno.turno_ia():
                    # Mientras la IA tiene el turno, nadie más lo toma (el OCR esperaría).
                    with open(candado, "a") as otro:
                        with self.assertRaises(BlockingIOError):
                            fcntl.flock(otro, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.assertTrue(post.call_args_list[0].args[0].endswith("/liberar"))
                # Al terminar se suelta.
                with open(candado, "a") as otro:
                    fcntl.flock(otro, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def test_sin_servicio_de_ocr_sigue(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(gpu_turno, "GPU_COMPARTIDA", True), \
                mock.patch.object(gpu_turno, "CANDADO", Path(tmp) / "gpu.lock"), \
                mock.patch.object(gpu_turno.requests, "post", side_effect=gpu_turno.requests.ConnectionError("apagado")), \
                mock.patch.object(gpu_turno.requests, "get", side_effect=gpu_turno.requests.ConnectionError("apagado")):
            with gpu_turno.turno_ia():
                hecho = True
        self.assertTrue(hecho)

    def test_recarga_el_modelo_que_quedo_en_el_procesador_una_vez(self):
        ps = mock.Mock(json=lambda: {"models": [{"name": "qwen3:4b", "size": 3_200_000_000, "size_vram": 95_000_000}]})
        vacio = mock.Mock(json=lambda: {"models": []})
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(gpu_turno, "GPU_COMPARTIDA", True), \
                mock.patch.object(gpu_turno, "CANDADO", Path(tmp) / "gpu.lock"), mock.patch.object(gpu_turno, "_ultima_recarga", {}), \
                mock.patch.object(gpu_turno.requests, "post") as post, mock.patch.object(gpu_turno.requests, "get", side_effect=[ps, vacio, ps]):
            with gpu_turno.turno_ia():
                pass
            with gpu_turno.turno_ia():  # dentro de los dos minutos: no se vuelve a recargar
                pass
        descargas = [c for c in post.call_args_list if c.args[0].endswith("/api/generate")]
        self.assertEqual(len(descargas), 1)
        self.assertEqual(descargas[0].kwargs["json"], {"model": "qwen3:4b", "keep_alive": 0})

    def test_no_recarga_si_ya_esta_en_la_gpu(self):
        ps = mock.Mock(json=lambda: {"models": [{"name": "qwen3:4b", "size": 3_200_000_000, "size_vram": 3_100_000_000}]})
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(gpu_turno, "GPU_COMPARTIDA", True), \
                mock.patch.object(gpu_turno, "CANDADO", Path(tmp) / "gpu.lock"), mock.patch.object(gpu_turno, "_ultima_recarga", {}), \
                mock.patch.object(gpu_turno.requests, "post") as post, mock.patch.object(gpu_turno.requests, "get", return_value=ps):
            with gpu_turno.turno_ia():
                pass
        self.assertFalse([c for c in post.call_args_list if c.args[0].endswith("/api/generate")])

