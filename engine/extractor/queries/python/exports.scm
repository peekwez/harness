; python exports: __all__ list; fallback is public-visibility symbols
(expression_statement
  (assignment
    left: (identifier) @all_name
    right: (list (string) @all_item) @all_list)
  (#eq? @all_name "__all__"))
