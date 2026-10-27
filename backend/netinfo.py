"""
Bilgisayarın yerel ağ (Wi-Fi/Ethernet) IPv4 adreslerini bulur — telefonun
aynı Wi-Fi'dan oyuna bağlanacağı adresi ekrana yazmak için.

Doğrudan çalıştırılırsa (start.bat bunu yapar) adresleri yazdırır:
    python netinfo.py 5000
"""
import socket
import sys


def _is_private(ip):
    if ip.startswith("192.168.") or ip.startswith("10."):
        return True
    if ip.startswith("172."):
        second = int(ip.split(".")[1])
        return 16 <= second <= 31
    return False


def get_lan_ips():
    """Olası yerel IP'leri döner; en olası olan (varsayılan rota) başta."""
    ips = []
    # UDP "connect" paket göndermez; sadece işletim sisteminin hangi arayüzü
    # kullanacağını sorar. İnternet olmasa da Wi-Fi'a bağlıyken çalışır.
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ips.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            if ip not in ips:
                ips.append(ip)
    except OSError:
        pass
    ips = [ip for ip in ips if _is_private(ip)]
    # VirtualBox/Hyper-V sanal ağları genelde .56. / 172.x; sona at.
    ips.sort(key=lambda ip: (ip.startswith("192.168.56.") or ip.startswith("172."),))
    return ips


if __name__ == "__main__":
    port = sys.argv[1] if len(sys.argv) > 1 else "5000"
    ips = get_lan_ips()
    if not ips:
        print("   Telefon icin  : (yerel ag adresi bulunamadi - Wi-Fi'a bagli misin?)")
    else:
        print(f"   Telefon icin  : http://{ips[0]}:{port}")
        for ip in ips[1:]:
            print(f"   (alternatif)  : http://{ip}:{port}")
