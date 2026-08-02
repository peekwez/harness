; go symbol captures: funcs, methods, and the spec nodes inside type/const/
; var declarations (a single declaration can hold several specs)
(function_declaration) @function
(method_declaration) @method
(type_declaration (type_spec) @type_spec)
(const_declaration (const_spec) @const_spec)
(var_declaration (var_spec) @var_spec)
