"""
test_scheduler.py — Tests para scheduler.py (cola de publicaciones).
"""

import os
import sys
import json
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


class TestPostQueue:
    """Verifica la cola de publicaciones."""

    def test_add_post(self, tmp_queue_dir):
        # Patch QUEUE_DIR antes de importar
        with patch("config.QUEUE_DIR", tmp_queue_dir):
            from utils.scheduler import PostQueue
            queue = PostQueue()
            queue.queue_file = str(tmp_queue_dir / "queue.json")
            queue.posts = []

            post_id = queue.add({
                "dia": "lunes",
                "producto": "emw",
                "copy_facebook": "Test copy",
            })

            assert post_id == 1
            assert len(queue.posts) == 1
            assert queue.posts[0]["status"] == "pendiente"

    def test_ids_no_colisionan(self, tmp_queue_dir):
        from utils.scheduler import PostQueue
        queue = PostQueue()
        queue.queue_file = str(tmp_queue_dir / "queue.json")
        queue.posts = []

        id1 = queue.add({"dia": "lunes", "producto": "emw"})
        id2 = queue.add({"dia": "martes", "producto": "graf"})
        id3 = queue.add({"dia": "miercoles", "producto": "sinergia"})

        assert id1 == 1
        assert id2 == 2
        assert id3 == 3

    def test_ids_con_borrados(self, tmp_queue_dir):
        """Verifica que max+1 funciona incluso si hay gaps."""
        from utils.scheduler import PostQueue
        queue = PostQueue()
        queue.queue_file = str(tmp_queue_dir / "queue.json")
        queue.posts = [
            {"id": 1, "status": "publicado"},
            {"id": 5, "status": "rechazado"},
        ]

        new_id = queue.add({"dia": "jueves", "producto": "graf"})
        assert new_id == 6  # max(1,5) + 1

    def test_aprobar_post(self, tmp_queue_dir):
        from utils.scheduler import PostQueue
        queue = PostQueue()
        queue.queue_file = str(tmp_queue_dir / "queue.json")
        queue.posts = []

        post_id = queue.add({"dia": "lunes", "producto": "emw"})
        assert queue.aprobar(post_id) is True
        assert queue.posts[0]["status"] == "aprobado"

    def test_rechazar_post(self, tmp_queue_dir):
        from utils.scheduler import PostQueue
        queue = PostQueue()
        queue.queue_file = str(tmp_queue_dir / "queue.json")
        queue.posts = []

        post_id = queue.add({"dia": "lunes", "producto": "emw"})
        assert queue.rechazar(post_id, "Calidad baja") is True
        assert queue.posts[0]["status"] == "rechazado"

    def test_marcar_publicado(self, tmp_queue_dir):
        from utils.scheduler import PostQueue
        queue = PostQueue()
        queue.queue_file = str(tmp_queue_dir / "queue.json")
        queue.posts = []

        post_id = queue.add({"dia": "lunes", "producto": "emw"})
        queue.aprobar(post_id)
        queue.marcar_publicado(post_id, {"post_id": "fb_123"})
        assert queue.posts[0]["status"] == "publicado"

    def test_filtros(self, tmp_queue_dir):
        from utils.scheduler import PostQueue
        queue = PostQueue()
        queue.queue_file = str(tmp_queue_dir / "queue.json")
        queue.posts = []

        id1 = queue.add({"dia": "lunes"})
        id2 = queue.add({"dia": "martes"})
        id3 = queue.add({"dia": "miercoles"})

        queue.aprobar(id2)
        queue.marcar_publicado(id3, {})

        assert len(queue.get_pendientes()) == 1
        assert len(queue.get_aprobados()) == 1
        assert len(queue.get_publicados()) == 1

    def test_stats(self, tmp_queue_dir):
        from utils.scheduler import PostQueue
        queue = PostQueue()
        queue.queue_file = str(tmp_queue_dir / "queue.json")
        queue.posts = []

        queue.add({"dia": "lunes"})
        queue.add({"dia": "martes"})
        id3 = queue.add({"dia": "miercoles"})
        queue.aprobar(id3)

        stats = queue.stats()
        assert stats["total"] == 3
        assert stats["pendientes"] == 2
        assert stats["aprobados"] == 1

    def test_persistencia(self, tmp_queue_dir):
        """Verifica que la cola se persiste y carga correctamente."""
        from utils.scheduler import PostQueue
        queue_file = str(tmp_queue_dir / "queue.json")

        q1 = PostQueue()
        q1.queue_file = queue_file
        q1.posts = []
        q1.add({"dia": "lunes", "producto": "emw"})
        q1._save()

        # Cargar desde archivo
        q2 = PostQueue()
        q2.queue_file = queue_file
        q2._load()
        assert len(q2.posts) == 1
        assert q2.posts[0]["producto"] == "emw"
