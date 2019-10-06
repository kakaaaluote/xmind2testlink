"""Add priority marker if topic's title start with specific characters."""

import os
import re
import shutil
import tempfile
from zipfile import ZipFile, ZIP_STORED, ZipInfo

import xml.etree.ElementTree as ET


class TestcaseMarker(object):

    MATCH_CHAR_LIST = ['F-', 'E-']

    def __init__(self, xmind):
        self.xmind = xmind

    # TODO: 1. 图片丢失；2. xhtml及其他的namespace都消失了，只有xmlns:html；3. 所有的xhtmltag都变成html了
    def overwrite_content_xml(self):
        temp_dir = tempfile.mkdtemp()

        with ZipFile(self.xmind, 'r') as zip:
            zip.extract("content.xml", temp_dir)

        temp_full_file_name = os.path.join(temp_dir, 'content.xml')
        root = self.get_content_xml_root_element(temp_full_file_name)
        root_topic_element = root.find('./sheet/topic')

        if root_topic_element is None:
            raise ValueError("找不到根节点，请确认！！")

        self.find_and_mark_testcase(root_topic_element)

        tree = ET.ElementTree(root)
        tree.write(temp_full_file_name, encoding='utf-8', xml_declaration=True)

        with UpdateableZipFile(self.xmind, "a") as o:
            o.write(temp_full_file_name, "content.xml")

        shutil.rmtree(temp_dir)

    def get_content_xml_root_element(self, xml_file):
        with open(xml_file, encoding='utf-8') as f:
            xml_string = f.read()

        xml_string = re.sub('\\sxmlns="[^"]+"', '', xml_string, count=1)
        root = ET.fromstring(xml_string)

        return root

    def find_and_mark_testcase(self, topic_element):
        if self.is_testcase_topic(topic_element):
            if not self.has_priority_marker(topic_element):
                self.add_priority_marker_to_topic(topic_element)
        else:
            if self.has_sub_topics(topic_element):
                sub_topic_element_list = self.get_sub_topics(topic_element)
                for sub_topic_element in sub_topic_element_list or []:
                    self.find_and_mark_testcase(sub_topic_element)

    def is_testcase_topic(self, topic_element):
        title_element = topic_element.find('./title')

        if title_element is not None and title_element.text:
            title = title_element.text
            for chars in self.MATCH_CHAR_LIST:
                if title.startswith(chars):
                    return True

        return False

    def has_sub_topics(self, topic_element):
        topics_element = topic_element.find('./children/topics')

        if topics_element is not None:
            return True

        return False

    def get_sub_topics(self, topic_element):
        return topic_element.findall('./children/topics/topic')

    def has_priority_marker(self, topic_element):
        marker_element_list = topic_element.findall('./marker-refs/marker-ref')

        if len(marker_element_list) > 0:
            for marker_element in marker_element_list:
                marker_id = marker_element.get('marker-id')
                if 'priority' in marker_id:
                    return True

        return False

    def add_priority_marker_to_topic(self, topic_element):
        marker_container_element = topic_element.find('./marker-refs')

        if marker_container_element is None:
            marker_container_element = ET.SubElement(topic_element, 'marker-refs')

        marker_element = ET.SubElement(marker_container_element, 'marker-ref')
        marker_element.set('marker-id', 'priority-2')


class UpdateableZipFile(ZipFile):
    """
    Add delete (via remove_file) and update (via writestr and write methods)
    To enable update features use UpdateableZipFile with the 'with statement',
    Upon  __exit__ (if updates were applied) a new zip file will override the exiting one with the updates
    """

    class DeleteMarker(object):
        pass

    def __init__(self, file, mode="r", compression=ZIP_STORED, allowZip64=False):
        # Init base
        super(UpdateableZipFile, self).__init__(file, mode=mode,
                                                compression=compression,
                                                allowZip64=allowZip64)
        # track file to override in zip
        self._replace = {}
        # Whether the with statement was called
        self._allow_updates = False

    def writestr(self, zinfo_or_arcname, bytes, compress_type=None, compresslevel=None):
        if isinstance(zinfo_or_arcname, ZipInfo):
            name = zinfo_or_arcname.filename
        else:
            name = zinfo_or_arcname
        # If the file exits, and needs to be overridden,
        # mark the entry, and create a temp-file for it
        # we allow this only if the with statement is used
        if self._allow_updates and name in self.namelist():
            temp_file = self._replace[name] = self._replace.get(name,
                                                                tempfile.TemporaryFile())
            temp_file.write(bytes)
        # Otherwise just act normally
        else:
            super(UpdateableZipFile, self).writestr(zinfo_or_arcname,
                                                    bytes, compress_type=compress_type)

    def write(self, filename, arcname=None, compress_type=None, compresslevel=None):
        arcname = arcname or filename
        # If the file exits, and needs to be overridden,
        # mark the entry, and create a temp-file for it
        # we allow this only if the with statement is used
        if self._allow_updates and arcname in self.namelist():
            temp_file = self._replace[arcname] = self._replace.get(arcname,
                                                                   tempfile.TemporaryFile())
            with open(filename, "rb") as source:
                shutil.copyfileobj(source, temp_file)
        # Otherwise just act normally
        else:
            super(UpdateableZipFile, self).write(filename,
                                                 arcname=arcname, compress_type=compress_type)

    def __enter__(self):
        # Allow updates
        self._allow_updates = True
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        # call base to close zip file, organically
        try:
            super(UpdateableZipFile, self).__exit__(exc_type, exc_val, exc_tb)
            if len(self._replace) > 0:
                self._rebuild_zip()
        finally:
            # In case rebuild zip failed,
            # be sure to still release all the temp files
            self._close_all_temp_files()
            self._allow_updates = False

    def _close_all_temp_files(self):
        for temp_file in self._replace.values():
            if hasattr(temp_file, 'close'):
                temp_file.close()

    def remove_file(self, path):
        self._replace[path] = self.DeleteMarker()

    def _rebuild_zip(self):
        tempdir = tempfile.mkdtemp()
        try:
            temp_zip_path = os.path.join(tempdir, 'new.zip')
            with ZipFile(self.filename, 'r') as zip_read:
                # Create new zip with assigned properties
                with ZipFile(temp_zip_path, 'w', compression=self.compression,
                             allowZip64=self._allowZip64) as zip_write:
                    for item in zip_read.infolist():
                        # Check if the file should be replaced / or deleted
                        replacement = self._replace.get(item.filename, None)
                        # If marked for deletion, do not copy file to new zipfile
                        if isinstance(replacement, self.DeleteMarker):
                            del self._replace[item.filename]
                            continue
                        # If marked for replacement, copy temp_file, instead of old file
                        elif replacement is not None:
                            del self._replace[item.filename]
                            # Write replacement to archive,
                            # and then close it (deleting the temp file)
                            replacement.seek(0)
                            data = replacement.read()
                            replacement.close()
                        else:
                            data = zip_read.read(item.filename)
                        zip_write.writestr(item, data)
            # Override the archive with the updated one
            shutil.move(temp_zip_path, self.filename)
        finally:
            shutil.rmtree(tempdir)


if __name__ == '__main__':
    marker = TestcaseMarker('../tests/test_zipfile/s.xmind')
    marker.overwrite_content_xml()