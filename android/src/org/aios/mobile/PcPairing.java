package org.aios.mobile;

import android.util.Base64;
import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.net.Proxy;
import java.net.URL;
import java.security.KeyStore;
import java.security.cert.CertificateFactory;
import java.security.cert.X509Certificate;
import javax.net.ssl.HttpsURLConnection;
import javax.net.ssl.SSLContext;
import javax.net.ssl.TrustManagerFactory;
import org.json.JSONObject;

final class PcPairing {
    final String endpoint;
    final String token;
    private final SSLContext tls;

    PcPairing(String text) throws Exception {
        JSONObject config = new JSONObject(text);
        String host = config.getString("host");
        int port = config.getInt("port");
        token = config.getString("token");
        if (!host.matches("(?:[0-9]{1,3}\\.){3}[0-9]{1,3}") || !token.matches("[0-9a-f]{64}") || port < 1 || port > 65535) {
            throw new IOException("PC 페어링 파일을 확인해 주세요.");
        }
        String[] octets = host.split("\\.");
        for (String octet : octets) {
            int number = Integer.parseInt(octet);
            if (number > 255 || !Integer.toString(number).equals(octet)) throw new IOException("잘못된 PC 주소입니다.");
        }
        int first = Integer.parseInt(octets[0]);
        int second = Integer.parseInt(octets[1]);
        if (!(first == 10 || first == 192 && second == 168 || first == 172 && second >= 16 && second <= 31)) {
            throw new IOException("같은 로컬 네트워크의 PC 주소가 필요합니다.");
        }
        endpoint = host + ":" + port;
        byte[] der = Base64.decode(config.getString("certificate_der"), Base64.DEFAULT);
        X509Certificate certificate = (X509Certificate) CertificateFactory.getInstance("X.509")
                .generateCertificate(new ByteArrayInputStream(der));
        certificate.checkValidity();
        KeyStore trust = KeyStore.getInstance(KeyStore.getDefaultType());
        trust.load(null, null);
        trust.setCertificateEntry("paired-windows-pc", certificate);
        TrustManagerFactory managers = TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm());
        managers.init(trust);
        tls = SSLContext.getInstance("TLS");
        tls.init(null, managers.getTrustManagers(), null);
    }

    HttpsURLConnection connect(String route) throws IOException {
        HttpsURLConnection connection = (HttpsURLConnection) new URL("https://" + endpoint + route).openConnection(Proxy.NO_PROXY);
        connection.setSSLSocketFactory(tls.getSocketFactory());
        return connection;
    }
}
