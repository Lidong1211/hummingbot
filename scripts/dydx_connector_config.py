import os
import sys
from hummingbot.client.config.config_crypt import ETHKeyFileSecretManger

def main():
    if len(sys.argv) < 5:
        print("用法: python scripts/dydx_connector_config.py <目标输出目录> <密码> <助记词/私钥> <dydx地址>")
        print("示例: python scripts/dydx_connector_config.py conf_taker Aa123456 'mnemonic phrase...' 'dydx1...'")
        sys.exit(1)

    target_dir = sys.argv[1]
    password = sys.argv[2]
    secret_phrase = sys.argv[3]
    chain_address = sys.argv[4]

    connectors_dir = os.path.join(target_dir, "connectors")
    os.makedirs(connectors_dir, exist_ok=True)

    manager = ETHKeyFileSecretManger(password=password)
    enc_phrase = manager.encrypt_secret_value("dydx_v4_perpetual_secret_phrase", secret_phrase)
    enc_addr = manager.encrypt_secret_value("dydx_v4_perpetual_chain_address", chain_address)

    yaml_content = f"""####################################
###   dydx_v4_perpetual config   ###
####################################

connector: dydx_v4_perpetual

dydx_v4_perpetual_secret_phrase: {enc_phrase}

dydx_v4_perpetual_chain_address: {enc_addr}
"""

    target_file = os.path.join(connectors_dir, "dydx_v4_perpetual.yml")
    with open(target_file, "w") as f:
        f.write(yaml_content)

    print(f"✅ 成功生成加密账户配置到: {target_file}")

if __name__ == "__main__":
    main()
