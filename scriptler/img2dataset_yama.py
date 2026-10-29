#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
img2dataset_yama.py — img2dataset'i semaforsuz ortamlar için yamalar.

Bazı konteyner/şartlı ortamlarda /dev/shm yoktur; bu durumda POSIX semaforları
(multiprocessing.Queue / Pool / SimpleQueue) kurulamaz ve img2dataset baştan
düşer (PermissionError: [Errno 13]). Bu yama, img2dataset'in multiprocessing
kullanan üç noktasını semafor GEREKTİRMEYEN iş parçacığı taklitleriyle değiştirir:

  * logger.LoggerProcess        -> ThreadLogger   (aynı arayüz)
  * main.multiprocessing_distributor -> thread_distributor
  * reader/downloader ThreadPool -> IplikHavuzu   (imap_unordered destekli)

İş ağ giriş/çıkış ağırlıklı olduğu için iş parçacıkları yeterince hızlıdır;
işlevsellik aynı kalır. Kullanım:

    import img2dataset_yama
    img2dataset_yama.yamala()
    from img2dataset import download
"""

import queue
import sys
import threading

from collections import deque
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

from tqdm import tqdm


class IplikHavuzu:
    """multiprocessing.pool.ThreadPool'ın semafor gerektirmeyen eşdeğeri.

    Kullanılan arayüz: ThreadPool(n), with bloğu, imap_unordered, terminate, join.
    """

    def __init__(self, processes=None, initializer=None, initargs=()):
        self._worker_sayisi = max(1, int(processes) if processes else 1)
        self._havuz = ThreadPoolExecutor(max_workers=self._worker_sayisi)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.terminate()
        self.join()
        return False

    def imap_unordered(self, func, iterable):
        """İşleri kaydırılan pencereyle yürüterek tamamlanma sırasına göre verir."""
        pencere = max(2, self._worker_sayisi * 2)
        iterator = iter(iterable)
        bekleyen = deque()
        bitti = False
        while True:
            while not bitti and len(bekleyen) < pencere:
                try:
                    oge = next(iterator)
                except StopIteration:
                    bitti = True
                    break
                bekleyen.append(self._havuz.submit(func, oge))
            if not bekleyen:
                return
            tamamlanan = [g for g in bekleyen if g.done()]
            if not tamamlanan:
                wait(bekleyen, return_when=FIRST_COMPLETED)
                tamamlanan = [g for g in bekleyen if g.done()]
            for gelecek in tamamlanan:
                bekleyen.remove(gelecek)
                yield gelecek.result()

    def map(self, func, iterable):
        """Basit map (kullanım kolaylığı için)."""
        return list(self.imap_unordered(func, iterable))

    def terminate(self):
        """Yeni işleri durdurur."""
        self._havuz.shutdown(wait=False)

    def join(self):
        """Tüm işlerin bitmesini bekler."""
        self._havuz.shutdown(wait=True)


class ThreadLogger:
    """LoggerProcess'in iş parçacığı tabanlı eşdeğeri (aynı arayüz)."""

    def __init__(self, output_folder, enable_wandb, wandb_project, config_parameters, log_interval=5):
        self.output_folder = output_folder
        self.enable_wandb = enable_wandb
        self.wandb_project = wandb_project
        self.config_parameters = config_parameters
        self.log_interval = log_interval
        self.done_shards = set()
        self.q = queue.Queue()
        self._thread = None
        self._bitti = threading.Event()

    def start(self):
        """Günlük iş parçacığını başlatır."""
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        # Orijinal davranış: kuyruğa sinyal gelince tamamlanır.
        while not self._bitti.is_set():
            try:
                mesaj = self.q.get(timeout=0.5)
            except queue.Empty:
                continue
            if mesaj is not None:
                return

    def finish(self):
        """Bitiş temizliği (bu taklitte yapılacak bir şey yok)."""

    def terminate(self):
        """Günlük iş parçacığını durdurur (hata/sinyal yolu)."""
        self._bitti.set()
        try:
            self.q.put_nowait("stop")
        except Exception:  # pylint: disable=broad-except
            pass

    def join(self, timeout=None):
        """Orijinaldeki gibi sinyal gönderip iş parçacığının bitmesini bekler."""
        self.q.put("stop")
        if self._thread is not None:
            self._thread.join(timeout)


def thread_distributor(processes_count, downloader, reader, _, max_shard_retry):
    """multiprocessing_distributor'ın iş parçacığı tabanlı eşdeğeri."""
    from img2dataset.distributor import retrier

    def calistir(gen):
        basarisiz = []
        with IplikHavuzu(processes_count) as havuz:
            for durum, satir in tqdm(havuz.imap_unordered(downloader, gen)):
                if durum is False:
                    basarisiz.append(satir)
        return basarisiz

    basarisiz_shardlar = calistir(reader)
    retrier(calistir, basarisiz_shardlar, max_shard_retry)


def yamala():
    """img2dataset modüllerindeki multiprocessing bileşenlerini taklitlerle değiştirir."""
    # Not: img2dataset/__init__.py içindeki `main` fonksiyonu, `img2dataset.main`
    # modül niteliğini gölgeler; bu yüzden modülleri sys.modules üzerinden alıyoruz.
    import img2dataset.main  # noqa: F401
    import img2dataset.reader  # noqa: F401
    import img2dataset.downloader  # noqa: F401

    i2d_main = sys.modules["img2dataset.main"]
    i2d_main.LoggerProcess = ThreadLogger
    i2d_main.multiprocessing_distributor = thread_distributor

    sys.modules["img2dataset.reader"].ThreadPool = IplikHavuzu
    sys.modules["img2dataset.downloader"].ThreadPool = IplikHavuzu
    return True