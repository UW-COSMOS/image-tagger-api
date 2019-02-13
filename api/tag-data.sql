INSERT INTO tags (tag_id, name, description, color) VALUES
(1, 'Body Text', 'The primary text of an article', '#aaaaaa'),
(2, 'Figure', 'A chart, graph, or other graphical display', '#a15231'),
(3, 'Figure Note', 'A footnote explanation of specific content in a figure', '#801515'),
(4, 'Figure Caption', 'A text description associated with an entire figure', '#c45778'),
(5, 'Table', 'A tabular representation of information', '#432F75'),
(6, 'Table Note', 'A footnote to explain a subset of table content', '#162c57'),
(7, 'Table Caption', 'A text description associated with an entire table', '#73548f'),
(8, 'Page Header', 'Document-wide summary information, including page no., at top of page', '#2a7534'),
(9, 'Page Footer', 'Document-wide summary information, including page no., at bottom of page', '#345455'),
(10, 'Section Header', 'Text identifying section within text of document', '#1aa778'),
(11, 'Equation', 'An equation', '#2C4770'),
(12, 'Equation label', 'An identifier for an equation', '#4D658D'),
(13, 'Abstract', 'Abstract of paper', '#D4A26A'),
(14, 'Reference text', 'References to other works', '#804D15'),
(15, 'Other', 'Textual metadata and image content that is not semantically meaningful', '#96990c')
ON CONFLICT DO NOTHING;
