; typescript symbol captures: functions, classes, interfaces, type aliases,
; top-level consts; export statements mark visibility
(function_declaration) @function
(class_declaration) @class
(interface_declaration) @interface
(type_alias_declaration) @type_alias
(program (lexical_declaration) @const)
(export_statement (lexical_declaration) @const)
(export_statement) @exported
