"""orderParams bytes32 packer (docs /docs/smart-contract/Order 'Unified Flags Layout'; enums /docs/smart-contract/common).
byte[0] category(Futures=2) [1] orderType(Limit=0,Market=1) [2] side(Buy=0,Sell=1) [3] timeInForce(GTC=1,IOC=2,FOK=3,PostOnly=4)
[4] marketUnit(Base=0) [5] bbo(None=0,Queue1=3) [6] isReduceOnly [7] positionSide(None=0) [9] stpMode (doc says placeOrder uses 0-7 but lists stp at 9 - verify on testnet)
Assumption to verify on testnet: byte[0] is the most-significant (leftmost) byte, as with Solidity bytes32 indexing.
placeOrder(address account, bytes32 clientOrderId, uint16 symbolId, bytes32 orderParams, uint256 price, uint256 qty, uint256 slippage, address builder, uint256 builderFeeRate)
  price/qty 18 decimals. Order contract 0x...1000. Sign with AGENT key, timestamp nonce.
cancelOrder(address account, uint128 orderId, bytes32 clientOrderId)  -- orderId=0 to cancel by clientOrderId
cancelAllOrders(address account, uint16 symbolId, OptionalCategory, OptionalOrderCategory, OptionalBool)"""
def pack(category=2, order_type=0, side=0, tif=4, market_unit=0, bbo=0, reduce_only=False, position_side=0, stp=0):
    b = bytearray(32)
    b[0], b[1], b[2], b[3], b[4], b[5], b[6], b[7], b[9] = category, order_type, side, tif, market_unit, bbo, int(reduce_only), position_side, stp
    return bytes(b)
if __name__ == "__main__":
    print("postonly buy :", "0x" + pack(side=0).hex()); print("postonly sell:", "0x" + pack(side=1).hex())
