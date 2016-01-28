from ..target import Label, Alignment
from ..target import Frame
from .instructions import dcd, Add, Sub, Mov, Mov2, Bl, Sw, Lw
from ..data_instructions import Db
from .instructions import RegisterSet
from .registers import R0, LR, SP, FP
from .registers import R9, R18, R19, R20, R21, R22, R23, R24, R25, R26, R27, RiscvRegister, get_register


class RiscvFrame(Frame):
    """ Riscv specific frame for functions.

        R5 and above are callee save (the function that is called
    """
    def __init__(self, name, arg_locs, live_in, rv, live_out):
        super().__init__(name, arg_locs, live_in, rv, live_out)
        # Allocatable registers:
        self.regs = [R9, R18, R19, R20, R21, R22, R23, R24, R25, R26, R27]
        self.fp = FP

        self.locVars = {}

        # Literal pool:
        self.constants = []
        self.literal_number = 0

    def new_virtual_register(self, twain=""):
        """ Retrieve a new virtual register """
        return super().new_virtual_register(RiscvRegister, twain=twain)

    def make_call(self, vcall):
        """ Implement actual call and save / restore live registers """
        # R0 is filled with return value, do not save it, it will conflict.
        # Now we now what variables are live:
        live_regs = self.live_regs_over(vcall)
        #register_set = set(live_regs)

        # Caller save registers:
        #if register_set:
            #yield Push(RegisterSet(register_set))
        i = 0
        for register in live_regs:
            #yield Push(register)
            yield Sw(SP,register,i)
            i-= 4
        yield Add(SP, SP, i)

        yield Bl(LR, vcall.function_name)

        # Restore caller save registers:
        #if register_set:
            #yield Pop(RegisterSet(register_set))
        i = 0
        for register in reversed(live_regs):
            yield Lw(SP,register,i)
            i+= 4
            #yield Pop(register)
        yield Add(SP, SP, i)

    def get_register(self, color):
        return get_register(color)

    def alloc_var(self, lvar, size):
        if lvar not in self.locVars:
            self.locVars[lvar] = self.stacksize
            self.stacksize = self.stacksize + size
        return self.locVars[lvar]

    def add_constant(self, value):
        """ Add constant literal to constant pool """
        for lab_name, val in self.constants:
            if value == val:
                return lab_name
        assert type(value) in [str, int, bytes], str(value)
        lab_name = '{}_literal_{}'.format(self.name, self.literal_number)
        self.literal_number += 1
        self.constants.append((lab_name, value))
        return lab_name

    def prologue(self):
        """ Returns prologue instruction sequence """
        # Label indication function:
        yield Label(self.name)
        #yield Push(RegisterSet({LR, R11}))
        i = 0
        for register in RegisterSet({LR, SP}):
            #Push(register)
            yield Sw(SP,register,i)
            i+= 4
        # Callee save registers:
        #yield Push(RegisterSet({R5, R6, R7, R8, R9, R10}))
        if self.stacksize > 0:
            yield Sub(SP, SP, self.stacksize)  # Reserve stack space
        yield Mov(FP, SP)                 # Setup frame pointer

    def litpool(self):
        """ Generate instruction for the current literals """
        # Align at 4 bytes
        if self.constants:
            yield Alignment(4)

        # Add constant literals:
        while self.constants:
            label, value = self.constants.pop(0)
            yield Label(label)
            if isinstance(value, int) or isinstance(value, str):
                yield dcd(value)
            elif isinstance(value, bytes):
                for byte in value:
                    yield Db(byte)
                yield Alignment(4)   # Align at 4 bytes
            else:  # pragma: no cover
                raise NotImplementedError('Constant of type {}'.format(value))

    def between_blocks(self):
        for ins in self.litpool():
            self.emit(ins)

    def epilogue(self):
        """ Return epilogue sequence for a frame. Adjust frame pointer
            and add constant pool
        """
        if self.stacksize > 0:
            yield Add(SP, SP, self.stacksize)
        #yield Pop(RegisterSet({R5, R6, R7, R8, R9, R10}))
        i = 0
        for register in RegisterSet({LR, SP}):
            #Pop(register)
            yield Lw(SP,register,i)
            i+= 4
        #yield Pop(RegisterSet({PC, R11}), extra_uses=[self.rv])
        # Add final literal pool:
        for instruction in self.litpool():
            yield instruction
        yield Alignment(4)   # Align at 4 bytes
