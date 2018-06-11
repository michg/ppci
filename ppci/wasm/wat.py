"""

2nd attempt to parse WAT (wasm text) as parsed s-expressions.

More or less a python version of this code:
https://github.com/WebAssembly/wabt/blob/master/src/wast-parser.cc
"""

from collections import defaultdict
from ..lang.sexpr import parse_sexpr
from .opcodes import OPERANDS, OPCODES
from .util import datastring2bytes
from .tuple_parser import TupleParser, Token
from . import components


def load_tuple(module, t):
    """ Load contents of tuple t into module """
    if not isinstance(t, tuple):
        raise TypeError('t must be tuple')

    loader = WatTupleLoader(module)

    if any(isinstance(e, components.Definition) for e in t):
        if not all(isinstance(e, components.Definition) for e in t):
            raise TypeError('All elements must be wasm components')

        for e in t:
            loader.add_definition(e)
        module.id = None
        module.definitions = loader.gather_definitions()
    else:
        # Parse nested strings at top level:
        t2 = []
        for e in t:
            if isinstance(e, str) and e.startswith('('):
                e = parse_sexpr(e)
            t2.append(e)
        t2 = tuple(t2)

        loader.load_module(t2)


class WatTupleLoader(TupleParser):
    def __init__(self, module):
        self.module = module
        self.definitions = defaultdict(list)

    def load_module(self, t):
        """ Load a module from a tuple """
        self._feed(t)

        self.expect(Token.LPAR)
        top_module_tag = self.munch('module')
        if top_module_tag:
            # Detect id:
            self.module.id = self._parse_optional_id()
        else:
            self.module.id = None

        while self.match(Token.LPAR):
            self.expect(Token.LPAR)
            kind = self.take()
            if kind == 'type':
                self.load_type()
            elif kind == 'data':
                self.load_data()
            elif kind == 'elem':
                self.load_elem()
            elif kind == 'export':
                self.load_export()
            elif kind == 'func':
                self.load_func()
            elif kind == 'global':
                self.load_global()
            elif kind == 'import':
                self.load_import()
            elif kind == 'memory':
                self.load_memory()
            elif kind == 'start':
                self.load_start()
            elif kind == 'table':
                self.load_table()
            else:
                raise NotImplementedError(kind)

        self.expect(Token.RPAR)
        self.expect(Token.EOF)

        self.module.definitions = self.gather_definitions()

    def gather_definitions(self):
        """ Take all definitions by section id order: """
        definitions = []
        for name in components.SECTION_IDS:
            for definition in self.definitions[name]:
                definitions.append(definition)
        # print(definitions)
        return definitions

    def add_definition(self, definition):
        # print(definition.to_string())
        self.definitions[definition.__name__].append(definition)

    def gen_id(self, kind):
        return '${}'.format(len(self.definitions[kind]))

    # Section types:
    def load_type(self):
        """ Load a tuple starting with 'type' """
        id = self._parse_optional_id(default=self.gen_id('type'))
        self.expect(Token.LPAR, 'func')
        params, results = self._parse_function_signature()
        self.expect(Token.RPAR, Token.RPAR)
        self.add_definition(components.Type(id, params, results))

    def _parse_optional_id(self, default=None):
        if self._at_id():
            id = self.take()
        else:
            id = default
        return id

    def _parse_optional_ref(self, default=None):
        """ Parse an optional reference, defaulting to 0 """
        if self._at_ref():
            return self.take()
        else:
            return default

    def _parse_type_use(self):
        if self.match(Token.LPAR, 'type'):
            self.expect(Token.LPAR, 'type')
            ref = self._parse_var()
            self.expect(Token.RPAR)
        elif self.match(Token.LPAR, 'param') or self.match(Token.LPAR, 'result'):
            params, results = self._parse_function_signature()
            ref = self.gen_id('type')
            self.add_definition(
                components.Type(ref, params, results))
        else:
            ref = self.gen_id('type')
            self.add_definition(
                components.Type(ref, [], []))
        return ref

    def _parse_function_signature(self):
        params = self._parse_param_list()
        results = self._parse_result_list()
        return params, results

    def _parse_param_list(self):
        return self._parse_type_bound_value_list('param')

    def _parse_type_bound_value_list(self, kind):
        """ Parse thing like (locals i32) (locals $foo i32) """
        params = []
        while self.munch(Token.LPAR, kind):
            if self.match(Token.RPAR):  # (param,)
                self.expect(Token.RPAR)
            else:
                if self._at_id():  # (param $id i32)
                    params.append((self.take(), self.take()))
                    self.expect(Token.RPAR)
                else:
                    # anonymous (param i32 i32 i32)
                    while not self.match(Token.RPAR):
                        p = self.take()
                        params.append((len(params), p))
                    self.expect(Token.RPAR)
        return params

    def _parse_result_list(self):
        result = []
        while self.munch(Token.LPAR, 'result'):
            while not self.match(Token.RPAR):
                result.append(self.take())
            self.expect(Token.RPAR)
        return result

    def load_import(self):
        modname = self.take()
        name = self.take()
        self.expect(Token.LPAR)
        kind = self.take()
        if kind == 'func':
            id = self._parse_optional_id(default=self.gen_id('func'))
            if self.match(Token.LPAR, 'type'):
                self.expect(Token.LPAR, 'type')
                ref = self._parse_var()  # Type reference
                self.expect(Token.RPAR)
            else:
                params, results = self._parse_function_signature()
                # TODO: is this correct? taking the id of the func?
                ref = id
                # ref = self.gen_id('type')
                self.add_definition(
                    components.Type(ref, params, results))
            info = (ref,)
        elif kind == 'table':
            id = self._parse_optional_id(default=self.gen_id('table'))
            min, max = self.parse_limits()
            table_kind = self.take()
            assert table_kind == 'anyfunc'
            info = (table_kind, min, max)
        elif kind == 'memory':
            id = self._parse_optional_id(default=self.gen_id('memory'))
            min, max = self.parse_limits()
            info = (min, max)
        elif kind == 'global':
            id = self._parse_optional_id(default=self.gen_id('global'))
            typ, mutable = self.parse_global_type()
            info = (typ, mutable)
        else:  # pragma: no cover
            raise NotImplementedError(kind)

        self.expect(Token.RPAR, Token.RPAR)
        self.add_definition(
            components.Import(modname, name, kind, id, info))

    def load_export(self):
        """ Parse a toplevel export """
        name = self.take()
        self.expect(Token.LPAR)
        kind = self.take()
        ref = self._parse_var()
        self.expect(Token.RPAR, Token.RPAR)
        self.add_definition(
            components.Export(name, kind, ref))

    def load_start(self):
        """ Parse a toplevel start """
        name = self._parse_var()
        self.expect(Token.RPAR)
        self.add_definition(components.Start(name))

    def load_table(self):
        """ Parse a table """
        id = self._parse_optional_id(default=self.gen_id('table'))
        self._parse_inline_export('table', id)
        if self.match(Token.LPAR, 'import'):  # handle inline imports
            modname, name = self._parse_inline_import()
            min, max = self.parse_limits()
            kind = self.take()
            self.expect(Token.RPAR)
            info = (kind, min, max)
            self.add_definition(
                components.Import(modname, name, 'table', id, info))
        elif self.munch('anyfunc'):
            # We have embedded data
            self.expect(Token.LPAR, 'elem')
            refs = self.parse_ref_list()
            self.expect(Token.RPAR)
            self.expect(Token.RPAR)
            offset = components.Instruction('i32.const', 0)
            min = max = len(refs)
            self.add_definition(
                components.Table(id, 'anyfunc', min, max))
            self.add_definition(
                components.Elem(id, offset, refs))
        else:
            min, max = self.parse_limits()
            kind = self.take()
            assert kind == 'anyfunc'
            self.expect(Token.RPAR)
            self.add_definition(
                components.Table(id, kind, min, max))

    def load_elem(self):
        """ Load an elem element """
        ref = self._parse_optional_ref(default=0)
        offset = self.parse_offset_expression()
        refs = self.parse_ref_list()
        while self._at_id():
            refs.append(self.take())
        self.expect(Token.RPAR)
        self.add_definition(
            components.Elem(ref, offset, refs))

    def parse_ref_list(self):
        """ Parse $1 $2 $foo $bar """
        refs = []
        while self._at_ref():
            refs.append(self.take())
        return refs

    def load_memory(self):
        """ Load a memory definition """
        id = self._parse_optional_id(default=self.gen_id('memory'))
        self._parse_inline_export('memory', id)
        if self.match(Token.LPAR, 'import'):  # handle inline imports
            modname, name = self._parse_inline_import()
            min, max = self.parse_limits()
            self.expect(Token.RPAR)
            info = (min, max)
            self.add_definition(
                components.Import(modname, name, 'memory', id, info))
        elif self.munch(Token.LPAR, 'data'):  # Inline data
            data = self.parse_data_blobs()
            self.expect(Token.RPAR)
            self.expect(Token.RPAR)
            pagesize = 65535
            max = 1
            assert len(data) < max * pagesize, 'TODO: round upward'
            min = max
            self.add_definition(
                components.Memory(id, min, max))
            offset = components.Instruction('i32.const', 0)
            self.add_definition(
                components.Data(id, offset, data))
        else:
            min, max = self.parse_limits()
            self.expect(Token.RPAR)
            self.add_definition(
                components.Memory(id, min, max))

    def parse_limits(self):
        if isinstance(self._lookahead(1)[0], int):
            min = self.take()
            assert isinstance(min, int)
            if isinstance(self._lookahead(1)[0], int):
                max = self.take()
                assert isinstance(max, int)
            else:
                max = None
        else:
            min = 0
            max = None
        return min, max

    def parse_global_type(self):
        if self.munch(Token.LPAR, 'mut'):
            typ = self.take()
            mutable = True
            self.expect(Token.RPAR)
        else:
            typ = self.take()
            mutable = False
        return (typ, mutable)

    def load_global(self):
        """ Load a global definition """
        id = self._parse_optional_id(default=self.gen_id('global'))
        self._parse_inline_export('global', id)
        if self.match(Token.LPAR, 'import'):  # handle inline imports
            modname, name = self._parse_inline_import()
            typ, mutable = self.parse_global_type()
            info = (typ, mutable)
            self.expect(Token.RPAR)
            self.add_definition(
                components.Import(modname, name, 'global', id, info))
        else:
            typ, mutable = self.parse_global_type()
            init = self._load_instruction_list()[0]
            self.expect(Token.RPAR)
            self.add_definition(
                components.Global(id, typ, mutable, init))

    def load_data(self):
        """ Load data """
        ref = self._parse_optional_ref(default=0)
        offset = self.parse_offset_expression()
        data = self.parse_data_blobs()
        self.expect(Token.RPAR)
        self.add_definition(
            components.Data(ref, offset, data))

    def parse_data_blobs(self):
        data = bytearray()
        while not self.match(Token.RPAR):
            txt = self.take()
            assert isinstance(txt, str)
            data.extend(datastring2bytes(txt))
        data = bytes(data)
        return data

    def parse_offset_expression(self):
        in_offset = self.munch(Token.LPAR, 'offset')
        assert self.at_instruction()
        offset = self._load_instruction_list()[0]
        if in_offset:
            self.expect(Token.RPAR)
        return offset

    def _parse_var(self):
        """ Parse a reference (int or $ref) """
        assert self._at_ref()
        return self.take()

    def load_func(self):
        id = self._parse_optional_id(default=self.gen_id('func'))
        self._parse_inline_export('func', id)

        if self.match(Token.LPAR, 'import'):  # handle inline imports
            modname, name = self._parse_inline_import()
            ref = self._parse_type_use()
            # TODO: wtf, parse types twice? why?
            params, results = self._parse_function_signature()
            self.expect(Token.RPAR)
            info = (ref,)
            self.add_definition(
                components.Import(modname, name, 'func', id, info))
        else:
            ref = self._parse_type_use()
            # TODO: wtf, parse types twice? why?
            params, results = self._parse_function_signature()
            localz = self._parse_locals()
            instructions = self._load_instruction_list()
            # for i in instructions:
            #    print(i.to_string())
            self.expect(Token.RPAR)
            self.add_definition(
                components.Func(id, ref, localz, instructions))

    def _parse_locals(self):
        return self._parse_type_bound_value_list('local')

    def _load_instruction_list(self):
        """ Load a list of instructions """
        instructions = []
        while self.at_instruction():
            instructions.extend(self._load_instruction())
        # print(instructions)
        return instructions

    def _load_instruction(self):
        """ Load a single (maybe nested) instruction """

        instructions = []
        # We can have instructions without parenthesis! OMG
        is_braced = self.munch(Token.LPAR)
        opcode = self.take()

        if opcode in ('block', 'loop', 'if'):
            block_id = self._parse_optional_id()
            # Result type:
            if self.munch(Token.LPAR, 'result'):
                result = self.take()
                self.expect(Token.RPAR)
            elif self.munch('emptyblock'):
                # TODO: is this legit?
                result = 'emptyblock'
            else:
                result = 'emptyblock'

            if is_braced:
                if opcode == 'if':
                    # Maybe we have a then instruction?
                    if self.munch(Token.RPAR):
                        instructions.append(
                            components.BlockInstruction('if', block_id, result))
                    else:
                        # Nested stuff
                        # First is the condition:
                        if not self.match(Token.LPAR, 'then'):
                            instructions.extend(self._load_instruction())

                        instructions.append(
                            components.BlockInstruction('if', block_id, result))

                        if self.munch(Token.RPAR):
                            pass
                        else:
                            # Optionally a nested then:
                            if self.munch(Token.LPAR, 'then'):
                                body = self._load_instruction_list()
                                instructions.extend(body)
                                self.expect(Token.RPAR)

                            # Load body and optional 'else':
                            body = self._load_instruction_list()
                            instructions.extend(body)
                            self.expect(Token.RPAR)

                            # Add implicit end:
                            instructions.append(components.Instruction('end'))
                else:
                    instructions.append(
                        components.BlockInstruction(opcode, block_id, result))
                    if self.munch(Token.RPAR):
                        pass
                    else:  # Nested instructions
                        body = self._load_instruction_list()
                        self.expect(Token.RPAR)
                        instructions.extend(body)
                        # Add implicit end:
                        instructions.append(components.Instruction('end'))
            else:
                instructions.append(
                    components.BlockInstruction(opcode, block_id, result))

        elif opcode in ('else',):
            block_id = self._parse_optional_id()
            instructions.append(components.Instruction(opcode))
            if is_braced:
                if not self.munch(Token.RPAR):
                    # Nested instructions
                    instructions.extend(self._load_instruction_list())
                    self.expect(Token.RPAR)
        elif opcode in ('end',):
            # TODO: we can check this label with the start label
            block_id = self._parse_optional_id()
            if is_braced:
                self.expect(Token.RPAR)
            instructions.append(components.Instruction(opcode))
        else:
            # Process any special case arguments:
            if '.load' in opcode or '.store' in opcode:
                args = []
                while isinstance(self._lookahead(1)[0], str):
                    args.append(self.take())
            elif opcode == 'call_indirect':
                ref = self._parse_type_use()
                args = (('type', ref), 0)
                # TODO: wtf, parse types twice? why?
                params, results = self._parse_function_signature()
                # print(params, results)
                # TODO: compare unbound func signature with type?
            elif opcode in ('br_table', 'memory.grow', 'memory.size'):
                # Simply take all arguments possible:
                args = []
                while isinstance(self._lookahead(1)[0], (int, str)):
                    args.append(self.take())
            else:
                operands = OPERANDS[opcode]

                args = []
                for op in operands:
                    assert not self.match(Token.LPAR)
                    if op == 'br_table':
                        # Take all ints and strings as jump labels:
                        targets = []
                        while isinstance(self._lookahead(1)[0], (int, str)):
                            targets.append(self.take())
                        args.extend(targets)
                    else:
                        arg = self.take()
                        args.append(arg)

            # Nested instruction!
            if is_braced:
                while not self.match(Token.RPAR):
                    instructions.extend(self._load_instruction())
                self.expect(Token.RPAR)

            i = components.Instruction(opcode, *args)
            instructions.append(i)
        return instructions

    # Inline stuff:
    def _parse_inline_import(self):
        self.expect(Token.LPAR, 'import')
        modname = self.take()
        name = self.take()
        self.expect(Token.RPAR)
        return modname, name

    def _parse_inline_export(self, kind, ref):
        while self.match(Token.LPAR, 'export'):
            self.expect(Token.LPAR, 'export')
            name = self.take()
            self.expect(Token.RPAR)
            self.add_definition(
                components.Export(name, kind, ref))

    def at_instruction(self):
        if self.match(Token.LPAR):
            la = self._lookahead(2)[1]
        else:
            la = self._lookahead(1)[0]
        return la in OPCODES

    def _at_id(self):
        x = self._lookahead(1)[0]
        return is_id(x)

    def _at_ref(self):
        x = self._lookahead(1)[0]
        return is_ref(x)


def is_id(x):
    # TODO: is id of None a good plan?
    return is_dollar(x) or (x is None)


def is_ref(x):
    """ Is the given value a reference """
    return is_dollar(x) or isinstance(x, int)


def is_dollar(x):
    return isinstance(x, str) and x.startswith('$')