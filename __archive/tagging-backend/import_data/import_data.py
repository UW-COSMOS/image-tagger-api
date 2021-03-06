"""
File: import_data.py
Author: Ian Ross
Email: iross@cs.wisc.edu
Description: # TODO

# Expected structure:
## stack_output/
#    xml/ %
#    html/
#        img/ $
#    output.csv $
#    tables.csv $
#    figures.csv $
## images/ &

# %: xml/annotation import
# $: kb import
# &: image import

"""
import uuid
import lxml.etree as etree
import psycopg2
import glob
import os, sys
import shutil
import fnmatch
import re
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import watchdog
import time
import string
from random import choice
from shutil import copyfile

VERBOSE = False

image_prefix_regex = re.compile('^\/images\/?')
obs_regex = re.compile(r'im[0-9a-zA-Z]{16}')

PG_CONN_STR = os.getenv("PG_CONN_STR")
if PG_CONN_STR is None:
    PG_CONN_STR="postgresql://postgres:@db:5432/annotations"

conn_attempts = 0
connected = False
while conn_attempts < 5 and not connected:
    try:
        print("Connecting to %s" % PG_CONN_STR)
        conn = psycopg2.connect(PG_CONN_STR)
        cur_images = conn.cursor()
        cur = conn.cursor()
        connected = True
    except:
        conn_attempts += 1
        print("Could not connect! Waiting 10 seconds and trying again. Attempt %s of 5" % conn_attempts)
        time.sleep(10)

tag_map = {}
cur.execute("SELECT tag_id, name FROM tag;")
for tag in cur:
    tag_map[tag[1]] = tag[0]

class Watcher():

    def __init__(self, output_dir, png_path, stack):
        self.output_dir = output_dir
        self.png_path = png_path
        self.stack = stack
        self.event_handler = watchdog.events.PatternMatchingEventHandler(patterns=["*.xml", "*.csv", "*.png"],
                ignore_patterns=["*/html*/*.png"],
                ignore_directories=True)
        self.event_handler.on_created = self.on_created
        self.observer = Observer()
        self.observer.schedule(self.event_handler, self.output_dir, recursive=True)
        print("Watching for output files in %s" % self.output_dir)
        self.observer.start()

    def on_created(self, event):
        if event.is_directory:
            return None

        elif event.event_type == 'created':
            # Take any action here when a file is first created.
            if event.src_path.endswith(".png"):
                import_image(os.path.basename(event.src_path), self.png_path)
            elif event.src_path.endswith(".xml"):
                import_xml(os.path.basename(event.src_path), os.path.dirname(event.src_path), self.png_path, self.stack)
            elif event.src_path.endswith(".csv"):
                if "output.csv" in event.src_path:
                    import_equations(event.src_path)
                elif "tables.csv" in event.src_path:
                    import_tables(event.src_path)
                elif "figures.csv" in event.src_path:
                    import_figures(event.src_path)
            else:
                if VERBOSE:
                    print("WARNING! Not sure what to do with file (%s)" % event.src_path)

    def stop(self):
        self.observer.stop()
        self.observer.join()

def obfuscate_png(filepath, png_path):
    """
    TODO: Docstring for obfuscate_png.

    Args:
        arg1 (TODO): TODO

    Returns: TODO

    """
    check = obs_regex.search(filepath)
    if check is not None: # already contains obfuscation
        return filepath

    image_str = 'im%s' % ''.join(choice(string.ascii_letters + string.digits) for i in range(16))
    new_filepath = filepath.replace(".png", "_%s.png" % image_str)
    shutil.move(os.path.join(png_path, filepath), os.path.join(png_path, new_filepath))
    return new_filepath

def parse_docid_and_page_no(filename):
    """
    TODO: Docstring for parse_docid.

    Args:
        arg1 (TODO): TODO

    Returns: TODO

    """
    doc_id, page_no = os.path.basename(filename).split(".pdf_")
    doc_id = doc_id.replace("_input", "")
    page_no = int(os.path.splitext(page_no)[0].split("_")[0])
    return doc_id, page_no

def import_image(image_filepath, png_path):
    """
    From an image's filepath (TODO: filename?), get the docid + page_no, check
    if the page image exists in the db, and return the image_id (inserting as needed)

    Args:
        arg1 (TODO): TODO

    Returns: image_id (UUID) - db-level internal id for the image.
    """
    # Get rid of leading `/images` if it exists
#    print("Importing image %s" % image_filepath)

    doc_id, page_no = parse_docid_and_page_no(image_filepath)

    cur.execute("SELECT image_id FROM image WHERE doc_id=%s AND page_no=%s", (doc_id, page_no))
    check = cur.fetchone()
    if check is None:
        image_id = uuid.uuid4()
        image_filepath = obfuscate_png(image_filepath, png_path)
    else: # repeat image
        return check[0]

    cur.execute("INSERT INTO image (image_id, doc_id, page_no, file_path) VALUES (%s, %s, %s, %s) ON CONFLICT (image_id) DO UPDATE SET image_id=EXCLUDED.image_id RETURNING image_id;", (str(image_id), doc_id, page_no, image_filepath))
    conn.commit()
    image_id = cur.fetchone()[0]
    return image_id

def insert_image_stack(image_id, stack_name):
    cur.execute("INSERT INTO image_stack (image_id, stack_id) VALUES (%s, %s) ON CONFLICT (image_id, stack_id) DO UPDATE SET image_id=EXCLUDED.image_id RETURNING image_stack_id", (str(image_id), stack_name))
    conn.commit()
    return cur.fetchone()[0]

def import_xml(xml_filename, xml_path, png_path, stack):
    with open(os.path.join(xml_path, xml_filename)) as fin:
        doc = etree.parse(fin)

    # try to find the image associated with this xml
    try:
        image_filepath = doc.xpath("//filename/text()")[0]
        _ = glob.glob("%s/%s" % (png_path, image_filepath))[0]
#            image_filepath = glob.glob("%s/%s*png" % (png_path, xml_filename.replace(xml_path, "").replace(".xml","")))[0]
    except: # something funny in the xml -- try to fall back on filename consistency
        image_filepath = os.path.basename(xml_filename).replace(".xml",".png")
        check = glob.glob("%s/%s" % (png_path, image_filepath.replace(".pdf", "*.pdf").replace(".png", "_*.png")))
        if check == [] or len(check)>1:
            if VERBOSE:
                print("Couldn't find page-level PNG associated with %s! Skipping." % xml_filename)
            return
        else:
            image_filepath = check[0].replace(png_path + "/", "")

    image_id = import_image(image_filepath, png_path)

    image_stack_id = insert_image_stack(image_id, stack)

    # loop through tags
    for record in doc.xpath("//object"):
        image_tag_id = uuid.uuid4()
        tag_name = record.xpath('name/text()')[0]
        tag_id = tag_map[tag_name]
        xmin = int(record.xpath('bndbox/xmin/text()')[0])
        ymin = int(record.xpath('bndbox/ymin/text()')[0])
        xmax = int(record.xpath('bndbox/xmax/text()')[0])
        ymax = int(record.xpath('bndbox/ymax/text()')[0])

        cur.execute("INSERT INTO image_tag (image_tag_id, image_stack_id, tag_id, geometry, tagger) VALUES (%s, %s, %s, ST_Collect(ARRAY[ST_MakeEnvelope(%s, %s, %s, %s)]), %s) ON CONFLICT DO NOTHING;", (str(image_tag_id), image_stack_id, tag_id, xmin, ymin, xmax, ymax, 'COSMOS'))
        conn.commit()

def import_xmls(xml_path, png_path, stack):
    """
    TODO: Docstring for import_xml.

    Args:
        arg1 (TODO): TODO

    Returns: TODO

    """

    for root, dirnames, filenames in os.walk(xml_path):
        for xml_filename in fnmatch.filter(filenames, '*.xml'):
            import_xml(xml_filename, root, png_path, stack)

    return 0

def import_figures(figure_kb_path):
    cur.execute("""
    CREATE TABLE IF NOT EXISTS equations.figures_tmp (
            target_img_path text,
            target_unicode text,
            target_tesseract text,
            assoc_img_path text,
            assoc_unicode text,
            assoc_tesseract text,
            html_file text
            );
            """)
    conn.commit()
    try:
        with open(figure_kb_path) as f:
            copy_sql = """
                COPY equations.figures_tmp(
                    target_img_path,
                    target_unicode,
                    target_tesseract,
                    assoc_img_path,
                    assoc_unicode,
                    assoc_tesseract,
                    html_file) FROM STDIN WITH DELIMITER ',' CSV HEADER;
                    """
            cur.copy_expert(sql=copy_sql, file=f)
            conn.commit()
    except IOError:
        if VERBOSE:
            print("WARNING! Could not find figures.csv KB dump.")

    cur.execute("INSERT INTO equations.figures SELECT * FROM equations.figures_tmp ON CONFLICT DO NOTHING; DROP TABLE equations.figures_tmp;")
    conn.commit()

def import_tables(table_kb_path):
    cur.execute("""
    CREATE TABLE IF NOT EXISTS equations.tables_tmp (
            target_img_path text,
            target_unicode text,
            target_tesseract text,
            assoc_img_path text,
            assoc_unicode text,
            assoc_tesseract text,
            html_file text
            );
            """)
    conn.commit()
    try:
        with open(table_kb_path) as f:
            copy_sql = """
                COPY equations.tables_tmp(
                    target_img_path,
                    target_unicode,
                    target_tesseract,
                    assoc_img_path,
                    assoc_unicode,
                    assoc_tesseract,
                    html_file) FROM STDIN WITH DELIMITER ',' CSV HEADER;
                    """
            cur.copy_expert(sql=copy_sql, file=f)
            conn.commit()
    except IOError:
        if VERBOSE:
            print("WARNING! Could not find tables.csv KB dump.")
    cur.execute("INSERT INTO equations.tables SELECT * FROM equations.tables_tmp ON CONFLICT DO NOTHING; DROP TABLE equations.tables_tmp;")
    conn.commit()

def import_equations(equation_kb_path):
    cur.execute("""
        CREATE TABLE IF NOT EXISTS equations.output_tmp (
            document_name text,
            id int,
            text text,
            document_id int,
            equation_id int,
            equation_text text,
            equation_offset text,
            sentence_id int,
            sentence_offset int,
            sentence_text text,
            score float,
            var_top	int,
            var_bottom int,
            var_left int,
            var_right int,
            var_page int,
            sent_xpath text,
            sent_words text[],
            sent_top text[],
            sent_table_id int,
            sent_section_id int,
            sent_row_start int,
            sent_row_end int,
            sent_right int[],
            sent_position int,
            sent_pos_tags text[],
            sent_paragraph_id int,
            sent_page int[],
            sent_ner_tags text[],
            sent_name text,
            sent_lemmas text[],
            sent_left int[],
            sent_html_tag text,
            sent_html_attrs text[],
            sent_document_id int,
            sent_dep_parents text[],
            sent_dep_labels text[],
            sent_col_start int,
            sent_col_end int,
            sent_char_offsets int[],
            sent_cell_id int,
            sent_bottom int[],
            sent_abs_char_offsets int[],
            equation_top int,
            equation_bottom	int,
            equation_left int,
            equation_right int,
            equation_page int,
            symbols text[],
            phrases text[],
            phrases_top text[],
            phrases_bottom text[],
            phrases_left text[],
            phrases_right text[],
            phrases_page text[],
            sentence_img text,
            equation_img text
            );
            """)
    conn.commit()
    try:
        with open(equation_kb_path) as f:
            copy_sql = """
                COPY equations.output_tmp(
                    document_name,
                    id,
                    text,
                    document_id,
                    equation_id,
                    equation_text,
                    equation_offset,
                    sentence_id,
                    sentence_offset,
                    sentence_text,
                    score,
                    var_top,
                    var_bottom,
                    var_left,
                    var_right,
                    var_page,
                    sent_xpath,
                    sent_words,
                    sent_top,
                    sent_table_id,
                    sent_section_id,
                    sent_row_start,
                    sent_row_end,
                    sent_right,
                    sent_position,
                    sent_pos_tags,
                    sent_paragraph_id,
                    sent_page,
                    sent_ner_tags,
                    sent_name,
                    sent_lemmas,
                    sent_left,
                    sent_html_tag,
                    sent_html_attrs,
                    sent_document_id,
                    sent_dep_parents,
                    sent_dep_labels,
                    sent_col_start,
                    sent_col_end,
                    sent_char_offsets,
                    sent_cell_id,
                    sent_bottom,
                    sent_abs_char_offsets,
                    equation_top,
                    equation_bottom,
                    equation_left,
                    equation_right,
                    equation_page,
                    symbols,
                    phrases,
                    phrases_top,
                    phrases_bottom,
                    phrases_left,
                    phrases_right,
                    phrases_page,
                    sentence_img,
                    equation_img) FROM STDIN WITH DELIMITER ',' CSV HEADER;
                    """
            cur.copy_expert(sql=copy_sql, file=f)
            conn.commit()
    except IOError:
        if VERBOSE:
            print("WARNING! Could not find output.csv KB dump.")
    cur.execute("INSERT INTO equations.output SELECT * FROM equations.output_tmp ON CONFLICT DO NOTHING; DROP TABLE equations.output_tmp;")
    conn.commit()
    cur.execute("""
        REFRESH MATERIALIZED VIEW equations.equation;
        REFRESH MATERIALIZED VIEW equations.phrase;
        REFRESH MATERIALIZED VIEW equations.sentence;
        REFRESH MATERIALIZED VIEW equations.variable;
        """)
    conn.commit()

def import_kb(output_path):
    """
    TODO: Docstring for import_kb.

    Args:
        arg1 (TODO): TODO

    Returns: TODO

    """
    import_figures(output_path + "figures.csv")
    import_tables(output_path + "tables.csv")
    import_equations(output_path + "output.csv")

    return 0

def main():

    # Need as input: pile of xml, pile of pngs
    if len(sys.argv) <= 2:
        print("Please specify output and page image directories! python import_segmentations.py [location_of_output] [location_of_pngs]")
        sys.exit(1)

    # TODO: stack support

    output_path = sys.argv[1]
    png_path = sys.argv[2]
    if len(sys.argv) == 5:
        stack = sys.argv[3]
        stack_type = sys.argv[4]
    else:
        stack = "default"
        stack_type = "prediction"

    cur.execute("SELECT id FROM stack_type")
    stack_types = [cur.fetchall()]
    if stack_type not in stack_type:
        print("Invalid stack type selected! Please specify one of: %s" % stack_types)
        print("Example usage: python import_segmentations.py [location_of_output] [location_of_pngs] [stack_name] %s" % stack_types)
        sys.exit(1)

    cur.execute("INSERT INTO stack (stack_id, stack_type) VALUES (%s, %s) ON CONFLICT DO NOTHING;", (stack, stack_type))
    conn.commit()

    # TODO: import images to tag? Or toggle via stack?
    # images can be the same, but they need to be a different image_stack

    for image_filepath in glob.glob(png_path + "*.png"):
        image_filepath = os.path.basename(image_filepath)
        image_id = import_image(image_filepath, png_path)
        if stack_type == "annotation": # if prediction, this will get called as part of the XML import
            insert_image_stack(image_id, stack)
    if stack_type == "prediction":
        import_xmls(output_path, png_path, stack)
        import_kb(output_path)

    # watch for changes in the output dir
#    w = Watcher(output_path, png_path, stack)
#    try:
#        while True:
#            time.sleep(60)
#            # temp hack to scan regularly
#            for image_filepath in glob.glob(png_path + "*.png"):
#                image_filepath = os.path.basename(image_filepath)
#                import_image(image_filepath, png_path)
#            import_xmls(output_path, png_path, stack)
#            import_kb(output_path)
#    except:
#        w.stop()
#        raise



if __name__ == '__main__':
    main()

