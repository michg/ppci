from ..token import Token, bit_range, bit_concat, bit


class RiscvToken(Token):
    size = 32
    opcode = bit_range(0, 7)
    rd = bit_range(7, 12)
    funct3 = bit_range(12, 15)
    rs1 = bit_range(15, 20)
    rs2 = bit_range(20, 25)
    funct7 = bit_range(25, 32)


class RiscvIToken(Token):
    size = 32
    opcode = bit_range(0, 7)
    rd = bit_range(7, 12)
    funct3 = bit_range(12, 15)
    rs1 = bit_range(15, 20)
    imm = bit_range(20, 32)


class RiscvSToken(Token):
    size = 32
    opcode = bit_range(0, 7)
    funct3 = bit_range(12, 15)
    rs1 = bit_range(15, 20)
    rs2 = bit_range(20, 25)
    imm = bit_concat(bit_range(25, 32), bit_range(7, 12))


class RiscvcToken(Token):
    size = 16
    op = bit_range(0, 2)
    rd = bit_range(7, 12)
    funct3 = bit_range(13, 16)
    imm = bit(12) + bit_range(2, 7)
