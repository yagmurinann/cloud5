# Proje 4: E-Ticaret Uygulaması (Otomatik Ölçeklendirme)

## Kapsam ve Amaç

Bu projenin temel amacı, modern bulut bilişim mimarilerinin kalbinde yer alan üç kritik prensibin (Esneklik, Yüksek Erişilebilirlik ve Maliyet Optimizasyonu) simüle edilmiş bir e-ticaret platformu üzerinde uygulamalı olarak gösterilmesidir. E-ticaret platformları, kampanya dönemlerinde (Örn: Efsane Cuma) anlık ve öngörülemez trafik artışları yaşarlar. 

- **Esneklik (Elasticity):** Sistem, artan müşteri trafiği karşısında otomatik olarak yeni sunucular (EC2) ekleyerek (Scale-out) performans kaybını önler.
- **Maliyet Optimizasyonu (Cost Optimization):** Trafik azaldığında, boşa çıkan sunucular sistemden otomatik olarak silinerek (Scale-in) gereksiz altyapı maliyetlerinin önüne geçilir.
- **Yüksek Erişilebilirlik (High Availability):** Application Load Balancer (ALB), kullanıcı isteklerini ayakta olan sağlıklı sunuculara eşit şekilde dağıtır. Eğer bir sunucu arızalanırsa, trafik otomatik olarak diğer sağlıklı sunuculara yönlendirilir ve kullanıcı kesinti hissetmez.

## Kullanılan Teknolojiler

Projenin altyapısının "Kod Olarak Altyapı (Infrastructure as Code - IaC)" mantığıyla ayağa kaldırılması için aşağıdaki teknolojiler kullanılmıştır:

- **Python & Boto3 SDK:** AWS servislerini programatik olarak yönetmek için temel dil ve kütüphane.
- **AWS EC2 (Elastic Compute Cloud):** Web uygulamasını barındıracak sanal sunucular.
- **Application Load Balancer (ALB):** Gelen HTTP isteklerini EC2 sunucuları arasında dengeleyen servis.
- **Auto Scaling Groups (ASG):** Sunucu sayısını dinamik olarak ayarlayan otomatik ölçeklendirme servisi.
- **CloudWatch Alarms:** CPU kullanım metriklerini takip ederek ASG'yi tetikleyen izleme servisi.

## Sistem Mimarisi Detayları

AWS altyapısı aşağıdaki bileşenlerin entegre çalışması ile kurulmuştur:

1. **Launch Template (Başlatma Şablonu):** 
   Sisteme eklenecek her yeni sunucunun temel bir kopyası (Blueprint) niteliğindedir. Yeni nesil ücretsiz katman (Free Tier) gereksinimleri için `t3.micro` sunucu tipi seçilmiş olup, IAM yetki çakışmalarını önlemek amacıyla `us-east-1` bölgesine ait stabil bir Amazon Linux 2 AMI ID'si koda sabitlenmiştir (hardcode). Şablona eklenen `UserData` bash scripti sayesinde, sunucu her açıldığında Apache web sunucusu (httpd) otomatik kurulur ve "Yagmur Inan E-Ticaret Platformuna Hos Geldiniz" mesajını barındıran anasayfa (index.html) oluşturulur.

2. **Target Group (Hedef Grubu):**
   Load Balancer'ın arkasında duran sunucuların havuzudur. Target Group, 80 portu üzerinden HTTP istekleriyle düzenli olarak "Health Check" (Sağlık Kontrolü) yaparak sunucuların ayakta olup olmadığını doğrular. Yanıt vermeyen sunuculara trafik gönderilmez.

3. **Application Load Balancer (ALB):**
   Kullanıcıların eriştiği tek internete açık (internet-facing) giriş noktasıdır. ALB, gelen trafiği `us-east-1` bölgesindeki default VPC'ye bağlı tüm alt ağlara (subnets) yerleştirilmiş olan Target Group'taki sağlıklı sunuculara yönlendirir. 

4. **Auto Scaling Group (ASG) ve Ölçeklendirme Politikası:**
   ASG, Launch Template'i kullanarak Target Group içerisine dinamik olarak sunucu ekler veya çıkarır. Sınırlar; Minimum 1, İstenen (Desired) 1 ve Maksimum 3 olarak belirlenmiştir. Sisteme eklenen `TargetTrackingScaling` politikası sayesinde, sunucuların ortalama CPU kullanımı %70'i aştığında CloudWatch alarmı tetiklenir ve sisteme otomatik yeni bir sunucu eklenir.

## Karşılaşılabilecek Olası Teknik Zorluklar ve Çözümleri

Mimarinin kodlanması ve ayağa kaldırılması sırasında bazı teknik sorunlar yaşanabilir:

1. **Güvenlik Grubu (Security Group) Port Çakışmaları veya Yetki Sorunları:**
   - *Sorun:* Eğer "ecommerce-web-sg" isminde bir güvenlik grubu önceden oluşturulmuşsa Boto3 `InvalidGroup.Duplicate` hatası fırlatır. Ayrıca, dışarıdan HTTP (80) portuna erişim izni verilmediyse Load Balancer üzerinden siteye ulaşılamaz (Time Out hatası).
   - *Çözüm:* Kod içerisine Try-Except blokları eklenerek hata yakalama yapılmıştır. Güvenlik grubuna `0.0.0.0/0` (herkese açık) CIDR bloğu ile 80 ve 22 (SSH) portları için açık yetkilendirme (Ingress rules) yapılmıştır.

2. **Alt Ağ (Subnet) ve Bölge Uyuşmazlıkları:**
   - *Sorun:* Load Balancer ve Auto Scaling grupları aynı VPC içerisindeki alt ağlarda barındırılmalıdır. Subnet ID'lerinin manuel verilmesi farklı AWS hesaplarında kodun hata vermesine yol açar.
   - *Çözüm:* Kod, hesabın aktif olduğu `us-east-1` bölgesindeki `isDefault=true` filtresi ile default VPC'yi ve ona bağlı alt ağları dinamik olarak çekecek (`describe_subnets`) şekilde yazılmıştır.

3. **IAM Yetki Kısıtlamaları (SSM AccessDenied):**
   - *Sorun:* Öğrenci veya kısıtlı hesaplarda AWS Systems Manager (SSM) üzerinden dinamik AMI ID çekerken `AccessDeniedException` hatası alınabilir.
   - *Çözüm:* SSM kullanımı yerine `us-east-1` bölgesi için çalışan stabil bir AMI ID'si koda doğrudan gömülmüştür.

4. **Ücretsiz Katman (Free Tier) Instance Kısıtlamaları:**
   - *Sorun:* AWS'nin güncel Free Tier politikaları nedeniyle eski hesaplarda çalışan `t2.micro` instance tipleri yeni hesaplarda `"not eligible for Free Tier"` hatası verebilmekte ve ASG sunucu başlatamamaktadır.
   - *Çözüm:* Launch Template içerisindeki InstanceType değeri güncel ücretsiz katman standardı olan `t3.micro` olarak değiştirilmiştir.

## Günlük İlerleme Günlüğü (Git Log Simülasyonu)

Proje geliştirme sürecindeki kronolojik yapılandırma ve kod commit adımları:

* **[Gün 1] `commit d4f8a1c`: Boto3 Kurulumu ve AWS Client Konfigürasyonu**
  - us-east-1 bölgesinde EC2, ELBv2 ve AutoScaling client'ları tanımlandı.
  - VPC ve alt ağları (Subnets) dinamik olarak çeken fonksiyon yazıldı.

* **[Gün 2] `commit a7b9e32`: Güvenlik Duvarı ve Launch Template Entegrasyonu**
  - HTTP ve SSH trafiğine izin veren Security Group koda eklendi.
  - Stabil Amazon Linux 2 AMI ID'si koda entegre edildi.
  - Apache kurulumunu yapan UserData bash scripti Base64 formatına çevrilerek Launch Template'e dahil edildi.

* **[Gün 3] `commit c31df9b`: Load Balancer ve Trafik Yönlendirme**
  - Sunucu sağlık kontrolü yapacak Target Group konfigüre edildi.
  - İnternete açık Application Load Balancer oluşturuldu.
  - ALB Listener ayarlanarak trafik 80 portundan Target Group'a yönlendirildi.

* **[Gün 4] `commit f928d7a`: Otomatik Ölçeklendirme (Auto Scaling) ve Politika Tanımı**
  - ASG oluşturularak Min:1, Max:3 kapasite sınırları belirlendi.
  - Target Tracking Policy eklenerek %70 CPU tetikleyicisi koda entegre edildi.
  - Hata yakalama (Try-Except) mekanizmaları ve kullanıcıyı bilgilendirici konsol çıktıları eklendi.

* **[Gün 5] `commit e1a50c8`: Raporlama ve Dokümantasyon**
  - Projenin teorik arka planını ve teknik detaylarını anlatan Markdown formatında final teslim raporu (`RAPOR.md`) hazırlandı.

* **[Gün 6] `commit 9362516`: Hata Çözümleri (Bug Fixes) ve Optimizasyon**
  - İsim çakışması (Duplicate Group) hatalarını önlemek için kaynak isimlerine rastgele sayılar (suffix) eklendi.
  - IAM yetki hataları için AMI ID dinamik çekimi yerine sabit (hardcode) değere geçirildi.
  - Yeni nesil Free Tier uyumluluğu için instance tipi `t3.micro` olarak güncellendi.
