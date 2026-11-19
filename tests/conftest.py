"""Isola os testes: banco e arquivos gerados vão para um diretório temporário."""
import os
import tempfile

os.environ["CHECKEXAME_DATA_DIR"] = tempfile.mkdtemp(prefix="checkexame-testes-")
os.environ["CHECKEXAME_BASES"] = os.path.join(os.environ["CHECKEXAME_DATA_DIR"], "sem_bases")
