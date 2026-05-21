import os


class ConfigLoader:
    @staticmethod
    def load_set_file(path):
        """?? MT5 ? .set ????????????????????"""
        if not os.path.exists(path):
            return {}

        try:
            for encoding in ConfigLoader._candidate_encodings(path):
                try:
                    data = {}
                    with open(path, "r", encoding=encoding) as handle:
                        for line in handle:
                            line = line.strip()
                            if not line or "=" not in line:
                                continue

                            key, value = line.split("=", 1)
                            key = key.strip()
                            value = ConfigLoader._strip_inline_comment(value.strip())

                            if value.lower() == "true":
                                data[key] = True
                            elif value.lower() == "false":
                                data[key] = False
                            else:
                                try:
                                    if "." in value:
                                        data[key] = float(value)
                                    else:
                                        data[key] = int(value)
                                except ValueError:
                                    data[key] = value
                    return data
                except UnicodeDecodeError:
                    continue
            return {}
        except Exception as exc:
            print(f"Error loading set file {path}: {exc}")
            return {}

    @staticmethod
    def _strip_inline_comment(value):
        """????????????????????????"""
        for marker in (" ;", " #"):
            if marker in value:
                value = value.split(marker, 1)[0].rstrip()
        return value

    @staticmethod
    def _is_utf16(path):
        """????????? UTF-16 BOM?"""
        try:
            with open(path, "rb") as handle:
                chunk = handle.read(2)
                return chunk in (b"\xff\xfe", b"\xfe\xff")
        except Exception:
            return False

    @staticmethod
    def _candidate_encodings(path):
        """??? BOM ???????? utf-8 / gbk / gb18030 ??????"""
        if ConfigLoader._is_utf16(path):
            return ["utf-16", "utf-8", "utf-8-sig", "gbk", "gb18030"]
        return ["utf-8", "utf-8-sig", "gbk", "gb18030", "utf-16"]
