import re
a_pattern = re.compile('<a[^><]*?href=[\'\"](.+?)[\'\"][^><]*?>', re.I)
frame_pattern = re.compile('<i?frame[^><]*?src=[\'\"](.*?[^\"\'<>]*?)[\'\"][^<>]*?>', re.I)
link_pattern = re.compile('<link[^><]*?href=[\'\"](.+?)[\'\"][^><]*?>', re.I)
script_pattern = re.compile('<script[^><\"]*?src=[\'\"](.*?\.js[^\"\'<>]*?)[\'\"]>', re.I)
img_pattern = re.compile('<img?[^<>]*?src?="\s*([^\"\'=\s]*?\.(jpg|jpeg|png|gif|svg|ico))".*?>', re.I)