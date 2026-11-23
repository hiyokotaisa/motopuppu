from io import SEEK_END

from flask_wtf.file import FileSize
from werkzeug.datastructures import FileStorage
from wtforms.validators import ValidationError


class StreamFileSize(FileSize):
    """Flask-WTFのバージョンによらず、全件readせずにサイズを検証する。"""

    def __call__(self, form, field):
        files = field.data if isinstance(field.data, list) else [field.data]
        if not files or not all(isinstance(file, FileStorage) and file for file in files):
            return
        for file in files:
            position = file.stream.tell()
            try:
                file.stream.seek(0, SEEK_END)
                size = file.stream.tell()
            finally:
                file.stream.seek(position)
            if size < self.min_size or size > self.max_size:
                raise ValidationError(
                    self.message or field.gettext(
                        f'File must be between {self.min_size} and {self.max_size} bytes.'
                    )
                )
