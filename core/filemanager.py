import json
import logging
import os
import time

from core.exceptions import InvalidJSONException, FileNotFoundException


class FileManager:
    """Provides methods for file and directory management."""

    @staticmethod
    def get_root():
        """Returns the root directory of the project."""
        return os.path.join(os.path.dirname(__file__), "..")

    @staticmethod
    def get_path(path):
        """Returns the full path of a file or directory in the project."""
        return os.path.join(FileManager.get_root(), path)

    @staticmethod
    def path_exists(path):
        """Returns True if the path exists, False otherwise."""
        return os.path.exists(path)

    @staticmethod
    def create_directory(directory):
        """Creates a directory if it does not exist."""
        if not os.path.exists(directory):
            os.makedirs(directory)

    @staticmethod
    def create_directories(directories):
        """Creates a list of directories in the root directory if they do not exist."""
        root_directory = FileManager.get_root()
        for directory in directories:
            directory = os.path.join(root_directory, directory)
            FileManager.create_directory(directory)

    @staticmethod
    def list_directory(directory, ends_with=None):
        """Returns a list of files in a directory. If ends_with is specified, only files ending with the specified
        string will be returned. Creates the directory if it does not exist."""
        full_path = os.path.join(FileManager.get_root(), directory)
        os.makedirs(full_path, exist_ok=True)
        files = os.listdir(full_path)
        if ends_with:
            files = [f for f in files if f.endswith(ends_with)]
        return files

    @staticmethod
    def __open_file(path, mode="r"):
        """Opens a file in the specified mode. Private do NOT use outside filemanager."""
        full_path = os.path.join(FileManager.get_root(), path)
        try:
            return open(full_path, mode)
        except:
            raise FileNotFoundException

    @staticmethod
    def read_file(path):
        """Reads the contents of a file and returns the data. Returns None if the file does not exist."""
        full_path = os.path.join(FileManager.get_root(), path)

        if not FileManager.path_exists(full_path):
            return None

        with FileManager.__open_file(full_path) as file:
            return file.read()

    @staticmethod
    def read_lines(path):
        """Reads the contents of a file and returns the lines. Returns None if the file does not exist."""
        full_path = os.path.join(FileManager.get_root(), path)

        if not FileManager.path_exists(full_path):
            return None

        with FileManager.__open_file(full_path) as file:
            return file.readlines()

    @staticmethod
    def remove_file(path):
        """Removes a file if it exists."""
        full_path = os.path.join(FileManager.get_root(), path)

        if FileManager.path_exists(full_path):
            os.remove(full_path)

    @staticmethod
    def load_json_file(path, **kwargs):
        """Loads a JSON file and returns the data. Returns None if the file does not exist."""
        full_path = os.path.join(FileManager.get_root(), path)

        if not FileManager.path_exists(full_path):
            return None

        with FileManager.__open_file(full_path) as file:
            try:
                return json.load(file, **kwargs)
            except json.decoder.JSONDecodeError:
                raise InvalidJSONException

    @staticmethod
    def save_json_file(data, path, **kwargs):
        """Saves data to a JSON file. If the file does not exist, it will be created.

        A escrita é atômica: grava num arquivo temporário e só então substitui o
        original via os.replace(). Antes, json.dump() truncava e reescrevia o
        arquivo in-place, deixando uma janela em que um leitor externo enxergava
        JSON parcial -- o webmanager roda como processo separado e relê o cache
        inteiro a cada request. Ver P0-4 em docs/auditoria_codigo_2026-08-08.md

        O sufixo com PID evita que duas escritas simultâneas (bot + webmanager,
        ou duas instâncias do bot) colidam no mesmo temporário. O nome termina
        em .tmp, então os leitores -- que filtram por .json -- o ignoram.

        Nunca levanta por causa de contenção: se o Windows recusar o replace
        repetidamente, degrada para escrita in-place (ver abaixo).
        """
        full_path = os.path.join(FileManager.get_root(), path)
        tmp_path = "%s.%d.tmp" % (full_path, os.getpid())

        try:
            with FileManager.__open_file(tmp_path, mode="w") as file:
                json.dump(data, file, indent=2, sort_keys=False, **kwargs)

            # No Windows, os.replace levanta PermissionError (WinError 5)
            # enquanto outro processo tiver o destino aberto: o open() do
            # Python não usa FILE_SHARE_DELETE, então o handle do leitor
            # impede a substituição. O webmanager relê todo o cache a cada
            # request, então isso acontece de verdade. O handle é efêmero
            # (open -> json.load -> close), e uma espera curta resolve.
            for attempt in range(10):
                try:
                    os.replace(tmp_path, full_path)
                    return
                except PermissionError:
                    time.sleep(0.05 * (attempt + 1))

            # Contenção persistente. Degrada para a escrita in-place antiga:
            # perde a atomicidade nesta escrita específica, mas o bot não pode
            # cair por causa de um leitor insistente -- seria trocar uma
            # corrida de leitura por um crash, o que é pior. O outro lado do
            # P0-4 cobre a consequência: o webmanager agora pula JSON parcial
            # em vez de apagar o arquivo.
            logging.warning(
                "save_json_file: replace atomico de %s negado apos 10 tentativas "
                "(leitor segurando o arquivo?); gravando in-place sem atomicidade",
                full_path,
            )
            with FileManager.__open_file(full_path, mode="w") as file:
                json.dump(data, file, indent=2, sort_keys=False, **kwargs)
        finally:
            # Não deixa temporário órfão -- nem no caminho de fallback, nem se
            # o dump falhar no meio (dado não serializável, disco cheio).
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

    @staticmethod
    def copy_file(src_path, dest_path):
        """Copies a file from the source path to the destination path."""
        full_src_path = os.path.join(FileManager.get_root(), src_path)
        full_dest_path = os.path.join(FileManager.get_root(), dest_path)

        if not FileManager.path_exists(full_src_path):
            return False

        with FileManager.__open_file(full_src_path) as src_file:
            with FileManager.__open_file(full_dest_path, mode="w") as dest_file:
                dest_file.write(src_file.read())
